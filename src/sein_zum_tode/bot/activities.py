import logging

from aiogram.enums import ChatType
from aiogram.types import Chat, Update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.errors import (
    InvalidStoredPayloadError,
    PermanentTelegramDeliveryError,
)
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    GROUP_UNSUPPORTED_RESPONSE_TEXT,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_ECHO_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_UNSUPPORTED_ACTIVITY_NAME,
    UNSUPPORTED_RESPONSE_TEXT,
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    InspectUpdateInput,
    PrepareResponseInput,
    TelegramResponse,
)
from sein_zum_tode.bot.ports import (
    TelegramMessageSender,
    TelegramPayloadCleaner,
    TelegramResponseReader,
    TelegramResponseStore,
    TelegramUpdateReader,
)
from sein_zum_tode.observability import LogContext


class InspectTelegramUpdateActivity:
    def __init__(
        self,
        update_reader: TelegramUpdateReader,
        logger: logging.Logger | None = None,
    ) -> None:
        self._update_reader = update_reader
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=INSPECT_UPDATE_ACTIVITY_NAME)
    async def inspect(self, input: InspectUpdateInput) -> InspectedUpdate:
        try:
            update = await self._update_reader.load_update(input.update_key)
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
        if chat is not None and chat.type != ChatType.PRIVATE:
            return InspectedUpdate(
                kind=InspectionKind.GROUP_UNSUPPORTED,
                update_key=input.update_key,
                chat_id=chat.id,
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
        update_reader: TelegramUpdateReader,
        response_store: TelegramResponseStore,
        ttl_seconds: int,
        help_text: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self._update_reader = update_reader
        self._response_store = response_store
        self._ttl_seconds = ttl_seconds
        self._help_text = help_text
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=PREPARE_ECHO_ACTIVITY_NAME)
    async def prepare_echo(self, input: PrepareResponseInput) -> None:
        text = UNSUPPORTED_RESPONSE_TEXT
        try:
            update = await self._update_reader.load_update(input.update_key)
        except InvalidStoredPayloadError:
            update = None
        if update is not None and update.message is not None and update.message.text is not None:
            text = update.message.text
        await self._store(input, text)
        self._log_prepared(input, InspectionKind.ECHO)

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        await self._prepare_static(input, InspectionKind.HELP, self._help_text)

    @activity.defn(name=PREPARE_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_unsupported(self, input: PrepareResponseInput) -> None:
        await self._prepare_static(
            input,
            InspectionKind.UNSUPPORTED,
            UNSUPPORTED_RESPONSE_TEXT,
        )

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        await self._prepare_static(
            input,
            InspectionKind.GROUP_UNSUPPORTED,
            GROUP_UNSUPPORTED_RESPONSE_TEXT,
        )

    async def _prepare_static(
        self,
        input: PrepareResponseInput,
        kind: InspectionKind,
        text: str,
    ) -> None:
        await self._store(input, text)
        self._log_prepared(input, kind)

    async def _store(self, input: PrepareResponseInput, text: str) -> None:
        await self._response_store.store_response(
            input.response_key,
            TelegramResponse(chat_id=input.chat_id, text=text),
            self._ttl_seconds,
        )

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
        response_reader: TelegramResponseReader,
        sender: TelegramMessageSender,
        logger: logging.Logger | None = None,
    ) -> None:
        self._response_reader = response_reader
        self._sender = sender
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        try:
            response = await self._response_reader.load_response(input.response_key)
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
            await self._sender.send_text(response.chat_id, response.text)
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
        cleaner: TelegramPayloadCleaner,
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
