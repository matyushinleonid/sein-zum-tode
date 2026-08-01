import logging

from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import Chat, Update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import BotContent, LocalizedBotContent
from sein_zum_tode.bot.errors import (
    InvalidStoredPayloadError,
    PermanentTelegramDeliveryError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_ABOUT_ACTIVITY_NAME,
    PREPARE_ECHO_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    PREPARE_LOCALIZATION_ACTIVITY_NAME,
    PREPARE_NOTIFICATIONS_ACTIVITY_NAME,
    PREPARE_UNSUPPORTED_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    InspectUpdateInput,
    PrepareResponseInput,
    TelegramButton,
    TelegramResponse,
)
from sein_zum_tode.bot.ports import (
    EphemeralPayloadCleaner,
    TelegramMessageSender,
)
from sein_zum_tode.localization.models import SupportedLocale
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.models import NotificationFrequency
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.documents import DocumentReader, DocumentWriter


class InspectTelegramUpdateActivity:
    def __init__(
        self,
        update_reader: DocumentReader[Update],
        logger: logging.Logger | None = None,
    ) -> None:
        self._update_reader = update_reader
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=INSPECT_UPDATE_ACTIVITY_NAME)
    async def inspect(self, input: InspectUpdateInput) -> InspectedUpdate:
        try:
            update = await self._update_reader.load(input.update_key)
        except InvalidStoredPayloadError:
            update = None
        if update is None:
            inspected = self._unsupported(input)
        else:
            inspected = self._classify(input, update)
        self._logger.info(
            "Telegram update inspected",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
            ).event(
                "telegram_update_inspected",
                inspection_kind=inspected.kind.value,
                chat_id=inspected.chat_id,
            ),
        )
        return inspected

    def _classify(self, input: InspectUpdateInput, update: Update) -> InspectedUpdate:
        chat = self._find_chat(update)
        callback_query_id = update.callback_query.id if update.callback_query is not None else None
        if chat is not None and chat.type != ChatType.PRIVATE:
            return InspectedUpdate(
                kind=InspectionKind.GROUP_UNSUPPORTED,
                update_key=input.update_key,
                chat_id=chat.id,
                callback_query_id=callback_query_id,
            )

        membership = update.my_chat_member
        if membership is not None:
            if membership.new_chat_member.status in {
                ChatMemberStatus.KICKED,
                ChatMemberStatus.LEFT,
            }:
                kind = InspectionKind.MORTAL_BLOCKED
            elif membership.new_chat_member.status == ChatMemberStatus.MEMBER:
                kind = InspectionKind.MORTAL_UNBLOCKED
            else:
                kind = InspectionKind.UNSUPPORTED
            return InspectedUpdate(
                kind=kind,
                update_key=input.update_key,
                chat_id=membership.chat.id,
            )

        callback = update.callback_query
        if callback is not None:
            locale = SupportedLocale.from_callback_data(callback.data)
            frequency = NotificationFrequency.from_callback_data(callback.data)
            return InspectedUpdate(
                kind=(
                    InspectionKind.LOCALIZATION_SELECTION
                    if locale is not None
                    else (
                        InspectionKind.NOTIFICATION_SELECTION
                        if frequency is not None
                        else InspectionKind.UNSUPPORTED
                    )
                ),
                update_key=input.update_key,
                chat_id=chat.id if chat is not None else input.user_id,
                callback_query_id=callback.id,
            )

        message = update.message
        if message is None:
            return InspectedUpdate(
                kind=InspectionKind.UNSUPPORTED,
                update_key=input.update_key,
                chat_id=chat.id if chat is not None else input.user_id,
            )
        if message.text == "/begin":
            kind = InspectionKind.BEGIN
        elif message.text == "/help":
            kind = InspectionKind.HELP
        elif message.text == "/about":
            kind = InspectionKind.ABOUT
        elif message.text == "/localization":
            kind = InspectionKind.LOCALIZATION
        elif message.text == "/notifications":
            kind = InspectionKind.NOTIFICATIONS
        elif message.text is not None:
            kind = InspectionKind.ECHO
        else:
            kind = InspectionKind.UNSUPPORTED
        return InspectedUpdate(
            kind=kind,
            update_key=input.update_key,
            chat_id=message.chat.id,
        )

    def _unsupported(self, input: InspectUpdateInput) -> InspectedUpdate:
        return InspectedUpdate(
            kind=InspectionKind.UNSUPPORTED,
            update_key=input.update_key,
            chat_id=input.user_id,
        )

    def _find_chat(self, update: Update) -> Chat | None:
        try:
            event = update.event
        except LookupError:
            return None
        chat = getattr(event, "chat", None)
        if isinstance(chat, Chat):
            return chat
        message = getattr(event, "message", None)
        chat = getattr(message, "chat", None)
        return chat if isinstance(chat, Chat) else None


class PrepareTelegramResponseActivities:
    def __init__(
        self,
        update_reader: DocumentReader[Update],
        response_store: DocumentWriter[TelegramResponse],
        ttl_seconds: int,
        content: BotContent,
        mortals: MortalRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self._update_reader = update_reader
        self._response_store = response_store
        self._ttl_seconds = ttl_seconds
        self._content = content
        self._mortals = mortals
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=PREPARE_ECHO_ACTIVITY_NAME)
    async def prepare_echo(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        text = localized.unsupported
        try:
            update = await self._update_reader.load(input.update_key)
        except InvalidStoredPayloadError:
            update = None
        if update is not None and update.message is not None and update.message.text is not None:
            text = update.message.text
        await self._store(input, text)
        self._log_prepared(input, InspectionKind.ECHO)

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        await self._prepare_localized(input, InspectionKind.HELP, "help")

    @activity.defn(name=PREPARE_ABOUT_ACTIVITY_NAME)
    async def prepare_about(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        await self._store(input, localized.about, parse_mode="HTML")
        self._log_prepared(input, InspectionKind.ABOUT)

    @activity.defn(name=PREPARE_LOCALIZATION_ACTIVITY_NAME)
    async def prepare_localization(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        settings = localized.localization
        keyboard = (
            (
                TelegramButton(
                    text=settings.russian,
                    callback_data=SupportedLocale.RUSSIAN.callback_data(),
                ),
                TelegramButton(
                    text=settings.english,
                    callback_data=SupportedLocale.ENGLISH.callback_data(),
                ),
            ),
        )
        await self._store(input, settings.prompt, keyboard=keyboard)
        self._log_prepared(input, InspectionKind.LOCALIZATION)

    @activity.defn(name=PREPARE_NOTIFICATIONS_ACTIVITY_NAME)
    async def prepare_notifications(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        settings = localized.notification_settings
        keyboard = (
            (
                TelegramButton(
                    text=settings.daily,
                    callback_data=NotificationFrequency.DAILY.callback_data(),
                ),
                TelegramButton(
                    text=settings.weekly,
                    callback_data=NotificationFrequency.WEEKLY.callback_data(),
                ),
            ),
            (
                TelegramButton(
                    text=settings.monthly,
                    callback_data=NotificationFrequency.MONTHLY.callback_data(),
                ),
                TelegramButton(
                    text=settings.never,
                    callback_data=NotificationFrequency.NEVER.callback_data(),
                ),
            ),
        )
        await self._store(input, settings.prompt, keyboard=keyboard)
        self._log_prepared(input, InspectionKind.NOTIFICATIONS)

    @activity.defn(name=PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME)
    async def prepare_limit_exhausted(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        await self._prepare_static(
            input,
            InspectionKind.LIMIT_EXHAUSTED,
            localized.prediction.limit_exhausted,
        )

    @activity.defn(name=PREPARE_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_unsupported(self, input: PrepareResponseInput) -> None:
        await self._prepare_localized(input, InspectionKind.UNSUPPORTED, "unsupported")

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        await self._prepare_localized(
            input,
            InspectionKind.GROUP_UNSUPPORTED,
            "group_unsupported",
        )

    async def _prepare_localized(
        self,
        input: PrepareResponseInput,
        kind: InspectionKind,
        field: str,
    ) -> None:
        localized = await self._localized(input.user_id)
        await self._prepare_static(input, kind, getattr(localized, field))

    async def _prepare_static(
        self,
        input: PrepareResponseInput,
        kind: InspectionKind,
        text: str,
    ) -> None:
        await self._store(input, text)
        self._log_prepared(input, kind)

    async def _store(
        self,
        input: PrepareResponseInput,
        text: str,
        *,
        parse_mode: str | None = None,
        keyboard: tuple[tuple[TelegramButton, ...], ...] = (),
    ) -> None:
        await self._response_store.store(
            input.response_key,
            TelegramResponse(
                chat_id=input.chat_id,
                text=text,
                parse_mode=parse_mode,
                keyboard=keyboard,
                callback_query_id=input.callback_query_id,
            ),
            self._ttl_seconds,
        )

    async def _localized(self, user_id: int | None) -> LocalizedBotContent:
        mortal = await self._mortals.get(user_id) if user_id is not None else None
        locale = (
            mortal.locale
            if mortal is not None and mortal.locale is not None
            else self._content.default_locale
        )
        return self._content.localized(locale)

    def _log_prepared(
        self,
        input: PrepareResponseInput,
        kind: InspectionKind,
    ) -> None:
        self._logger.info(
            "Telegram response prepared",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
            ).event(
                "telegram_response_prepared",
                inspection_kind=kind.value,
                chat_id=input.chat_id,
            ),
        )


class DeliverTelegramResponseActivity:
    def __init__(
        self,
        response_reader: DocumentReader[TelegramResponse],
        sender: TelegramMessageSender,
        logger: logging.Logger | None = None,
    ) -> None:
        self._response_reader = response_reader
        self._sender = sender
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        try:
            response = await self._response_reader.load(input.response_key)
        except InvalidStoredPayloadError as error:
            raise ApplicationError(
                f"Invalid Telegram response at {input.response_key}",
                type="InvalidTelegramResponse",
                non_retryable=True,
            ) from error
        if response is None:
            raise ApplicationError(
                f"Telegram response expired at {input.response_key}",
                type="TelegramResponseNotFound",
                non_retryable=True,
            )
        try:
            await self._sender.send(response)
        except TelegramRecipientUnavailableError as error:
            raise ApplicationError(
                f"Telegram recipient {response.chat_id} is unavailable",
                type="TelegramRecipientUnavailable",
                non_retryable=True,
            ) from error
        except PermanentTelegramDeliveryError as error:
            raise ApplicationError(
                f"Telegram permanently rejected response for chat {response.chat_id}",
                type="PermanentTelegramDeliveryError",
                non_retryable=True,
            ) from error
        self._logger.info(
            "Telegram response delivered",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
            ).event(
                "telegram_response_delivered",
                chat_id=response.chat_id,
            ),
        )


class CleanupTelegramPayloadsActivity:
    def __init__(
        self,
        cleaner: EphemeralPayloadCleaner,
        logger: logging.Logger | None = None,
    ) -> None:
        self._cleaner = cleaner
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        await self._cleaner.delete(input.keys)
        self._logger.debug(
            "Telegram payloads cleaned up",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
            ).event("telegram_payloads_cleaned_up"),
        )
