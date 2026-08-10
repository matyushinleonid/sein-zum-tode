import logging
from datetime import timedelta
from time import monotonic

from aiogram.enums import ChatMemberStatus, ChatType, ContentType
from aiogram.types import Chat, Message, Update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import BotContent, LocalizedBotContent, NotificationTier
from sein_zum_tode.bot.errors import (
    InvalidStoredPayloadError,
    PermanentTelegramDeliveryError,
    TelegramRateLimitedError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.keyboards import TelegramKeyboardCatalog
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_ABOUT_ACTIVITY_NAME,
    PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    PREPARE_LOCALIZATION_ACTIVITY_NAME,
    PREPARE_NOTIFICATIONS_ACTIVITY_NAME,
    PREPARE_PAYLOAD_EXPIRED_ACTIVITY_NAME,
    PREPARE_SCREAM_DENIED_ACTIVITY_NAME,
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
from sein_zum_tode.bot.temporal_errors import (
    TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE,
)
from sein_zum_tode.broadcasts.models import ScreamRequest
from sein_zum_tode.localization.models import SupportedLocale
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.models import (
    NotificationFrequency,
    is_custom_notification_callback,
)
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.documents import DocumentReader, DocumentWriter
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics


class InspectTelegramUpdateActivity:
    def __init__(
        self,
        update_reader: DocumentReader[Update],
        logger: logging.Logger | None = None,
        *,
        keyboards: TelegramKeyboardCatalog,
        admin_user_ids: frozenset[int] = frozenset(),
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._update_reader = update_reader
        self._keyboards = keyboards
        self._admin_user_ids = admin_user_ids
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=INSPECT_UPDATE_ACTIVITY_NAME)
    async def inspect(self, input: InspectUpdateInput) -> InspectedUpdate:
        try:
            update = await self._update_reader.load(input.update_key)
        except InvalidStoredPayloadError:
            inspected = self._unsupported(input)
        else:
            if update is None:
                inspected = self._expired(input)
                self._metrics.payload_expired(kind="telegram_update")
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
        self._metrics.inspected(kind=inspected.kind.value)
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
            selection = self._keyboards.selection(update)
            return InspectedUpdate(
                kind=self._selection_kind(selection.data if selection is not None else None),
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
        if self._is_scream_command(message.text):
            return self._scream(input, message)
        if self._is_sample_command(message.text):
            return self._sample(input, message)
        selection = self._keyboards.selection(update)
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
        elif message.text is not None and message.text.startswith("/"):
            kind = InspectionKind.UNKNOWN_COMMAND
        else:
            kind = (
                self._selection_kind(selection.data)
                if selection is not None
                else (
                    InspectionKind.TEXT if message.text is not None else InspectionKind.UNSUPPORTED
                )
            )
        return InspectedUpdate(
            kind=kind,
            update_key=input.update_key,
            chat_id=message.chat.id,
            reply_keyboard_selection=(
                selection.from_reply_keyboard if selection is not None else False
            ),
        )

    @staticmethod
    def _selection_kind(data: str | None) -> InspectionKind:
        if SupportedLocale.from_callback_data(data) is not None:
            return InspectionKind.LOCALIZATION_SELECTION
        if is_custom_notification_callback(data):
            return InspectionKind.CUSTOM_NOTIFICATION_SELECTION
        if NotificationFrequency.from_callback_data(data) is not None:
            return InspectionKind.NOTIFICATION_SELECTION
        return InspectionKind.UNSUPPORTED

    def _scream(self, input: InspectUpdateInput, message: Message) -> InspectedUpdate:
        author = message.from_user
        if author is None or author.id not in self._admin_user_ids:
            return InspectedUpdate(
                kind=InspectionKind.SCREAM_DENIED,
                update_key=input.update_key,
                chat_id=message.chat.id,
            )
        request = self._scream_request(message)
        return InspectedUpdate(
            kind=(
                InspectionKind.SCREAM if request is not None else InspectionKind.SCREAM_UNSUPPORTED
            ),
            update_key=input.update_key,
            chat_id=message.chat.id,
            scream_request=request,
        )

    def _scream_request(self, message: Message) -> ScreamRequest | None:
        parts = message.text.split() if message.text is not None else []
        if len(parts) != 2:
            return None
        try:
            locale = SupportedLocale(parts[1])
        except ValueError:
            return None
        source = message.reply_to_message
        if (
            source is None
            or source.media_group_id is not None
            or source.content_type not in self._scream_content_types()
        ):
            return None
        return ScreamRequest(
            locale=locale.value,
            source_chat_id=source.chat.id,
            source_message_id=source.message_id,
        )

    def _is_scream_command(self, text: str | None) -> bool:
        if text is None:
            return False
        command = text.split(maxsplit=1)[0]
        return command == "/scream"

    def _sample(self, input: InspectUpdateInput, message: Message) -> InspectedUpdate:
        author = message.from_user
        parts = message.text.split() if message.text is not None else []
        if author is None or author.id not in self._admin_user_ids or len(parts) != 2:
            return InspectedUpdate(
                kind=InspectionKind.UNSUPPORTED,
                update_key=input.update_key,
                chat_id=message.chat.id,
            )
        try:
            tier = NotificationTier(parts[1].lower())
        except ValueError:
            return InspectedUpdate(
                kind=InspectionKind.UNSUPPORTED,
                update_key=input.update_key,
                chat_id=message.chat.id,
            )
        return InspectedUpdate(
            kind=InspectionKind.NOTIFICATION_SAMPLE,
            update_key=input.update_key,
            chat_id=message.chat.id,
            notification_sample=tier,
        )

    def _is_sample_command(self, text: str | None) -> bool:
        if text is None:
            return False
        command = text.split(maxsplit=1)[0]
        return command == "/sample"

    def _scream_content_types(self) -> frozenset[ContentType]:
        return frozenset(
            {
                ContentType.TEXT,
                ContentType.PHOTO,
                ContentType.VIDEO,
                ContentType.ANIMATION,
                ContentType.AUDIO,
                ContentType.DOCUMENT,
                ContentType.VOICE,
                ContentType.VIDEO_NOTE,
                ContentType.STICKER,
            }
        )

    def _unsupported(self, input: InspectUpdateInput) -> InspectedUpdate:
        return InspectedUpdate(
            kind=InspectionKind.UNSUPPORTED,
            update_key=input.update_key,
            chat_id=input.user_id,
        )

    def _expired(self, input: InspectUpdateInput) -> InspectedUpdate:
        return InspectedUpdate(
            kind=InspectionKind.PAYLOAD_EXPIRED,
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
        response_store: DocumentWriter[TelegramResponse],
        ttl_seconds: int,
        content: BotContent,
        mortals: MortalRepository,
        keyboards: TelegramKeyboardCatalog,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._response_store = response_store
        self._ttl_seconds = ttl_seconds
        self._content = content
        self._mortals = mortals
        self._keyboards = keyboards
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        await self._prepare_localized(
            input,
            InspectionKind.HELP,
            "help",
            parse_mode="HTML",
        )

    @activity.defn(name=PREPARE_ABOUT_ACTIVITY_NAME)
    async def prepare_about(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        await self._store(input, localized.about, parse_mode="HTML")
        self._log_prepared(input, InspectionKind.ABOUT)

    @activity.defn(name=PREPARE_LOCALIZATION_ACTIVITY_NAME)
    async def prepare_localization(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        settings = localized.localization
        keyboard = self._keyboards.localization(localized)
        await self._store(input, settings.prompt, keyboard=keyboard)
        self._log_prepared(input, InspectionKind.LOCALIZATION)

    @activity.defn(name=PREPARE_NOTIFICATIONS_ACTIVITY_NAME)
    async def prepare_notifications(self, input: PrepareResponseInput) -> None:
        mortal = await self._mortal(input.user_id)
        localized = self._content.localized(mortal.locale)
        settings = localized.notification_settings
        keyboard = self._keyboards.notifications(localized)
        await self._store(
            input,
            settings.prompt_text(mortal.timezone),
            keyboard=keyboard,
        )
        self._log_prepared(input, InspectionKind.NOTIFICATIONS)

    @activity.defn(name=PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME)
    async def prepare_custom_notification(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        await self._store(
            input,
            localized.notification_settings.custom_prompt,
        )
        self._log_prepared(input, InspectionKind.CUSTOM_NOTIFICATION_SELECTION)

    @activity.defn(name=PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME)
    async def prepare_limit_exhausted(self, input: PrepareResponseInput) -> None:
        localized = await self._localized(input.user_id)
        await self._prepare_static(
            input,
            InspectionKind.LIMIT_EXHAUSTED,
            localized.llm.limit_exhausted,
        )

    @activity.defn(name=PREPARE_PAYLOAD_EXPIRED_ACTIVITY_NAME)
    async def prepare_payload_expired(self, input: PrepareResponseInput) -> None:
        await self._prepare_localized(
            input,
            InspectionKind.PAYLOAD_EXPIRED,
            "payload_expired",
        )

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        await self._prepare_localized(
            input,
            InspectionKind.GROUP_UNSUPPORTED,
            "group_unsupported",
        )

    @activity.defn(name=PREPARE_SCREAM_DENIED_ACTIVITY_NAME)
    async def prepare_scream_denied(self, input: PrepareResponseInput) -> None:
        await self._prepare_localized(
            input,
            InspectionKind.SCREAM_DENIED,
            "scream_denied",
        )

    async def _prepare_localized(
        self,
        input: PrepareResponseInput,
        kind: InspectionKind,
        field: str,
        *,
        parse_mode: str | None = None,
    ) -> None:
        localized = await self._localized(input.user_id)
        await self._prepare_static(
            input,
            kind,
            getattr(localized, field),
            parse_mode=parse_mode,
        )

    async def _prepare_static(
        self,
        input: PrepareResponseInput,
        kind: InspectionKind,
        text: str,
        *,
        parse_mode: str | None = None,
    ) -> None:
        await self._store(input, text, parse_mode=parse_mode)
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
                keyboard_mode=self._keyboards.mode,
                remove_reply_keyboard=input.remove_reply_keyboard,
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

    async def _mortal(self, user_id: int | None) -> Mortal:
        mortal = await self._mortals.get(user_id) if user_id is not None else None
        if mortal is None:
            raise ApplicationError(
                "Mortal was not found",
                type="MortalNotFound",
                non_retryable=True,
            )
        return mortal

    def _log_prepared(
        self,
        input: PrepareResponseInput,
        kind: InspectionKind,
    ) -> None:
        self._metrics.response_prepared(kind=kind.value)
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
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._response_reader = response_reader
        self._sender = sender
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        started = monotonic()
        try:
            response = await self._response_reader.load(input.response_key)
        except InvalidStoredPayloadError as error:
            self._record_delivery(input, "failed", "invalid_payload", started)
            raise ApplicationError(
                f"Invalid Telegram response at {input.response_key}",
                type="InvalidTelegramResponse",
                non_retryable=True,
            ) from error
        if response is None:
            self._record_delivery(input, "failed", "expired_payload", started)
            raise ApplicationError(
                f"Telegram response expired at {input.response_key}",
                type="TelegramResponseNotFound",
                non_retryable=True,
            )
        try:
            await self._sender.send(response)
        except TelegramRateLimitedError as error:
            self._record_delivery(input, "failed", "rate_limited", started)
            raise ApplicationError(
                "Telegram delivery was rate limited",
                type="TelegramRateLimited",
                next_retry_delay=timedelta(seconds=error.retry_after_seconds),
            ) from error
        except TelegramRecipientUnavailableError as error:
            self._record_delivery(input, "failed", "recipient_unavailable", started)
            raise ApplicationError(
                f"Telegram recipient {response.chat_id} is unavailable",
                type=TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE,
                non_retryable=True,
            ) from error
        except PermanentTelegramDeliveryError as error:
            self._record_delivery(input, "failed", "permanent_rejection", started)
            raise ApplicationError(
                f"Telegram permanently rejected response for chat {response.chat_id}",
                type="PermanentTelegramDeliveryError",
                non_retryable=True,
            ) from error
        self._record_delivery(input, "success", "none", started)
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

    def _record_delivery(
        self,
        input: DeliverResponseInput,
        outcome: str,
        error_kind: str,
        started: float,
    ) -> None:
        self._metrics.delivery(
            kind=input.delivery_kind.value,
            outcome=outcome,
            error_kind=error_kind,
            elapsed_seconds=monotonic() - started,
        )


class CleanupTelegramPayloadsActivity:
    def __init__(
        self,
        cleaner: EphemeralPayloadCleaner,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._cleaner = cleaner
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        try:
            await self._cleaner.delete(input.keys)
        except Exception:
            self._metrics.cleanup(kind=input.payload_kind.value, outcome="failed")
            raise
        self._metrics.cleanup(kind=input.payload_kind.value, outcome="success")
        self._logger.info(
            "Telegram payloads cleaned up",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
            ).event("telegram_payloads_cleaned_up"),
        )
