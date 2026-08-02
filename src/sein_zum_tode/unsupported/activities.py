import logging

from temporalio import activity

from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.bot.errors import InvalidStoredPayloadError
from sein_zum_tode.bot.models import (
    PrepareResponseInput,
    TelegramResponse,
)
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.observability import LogContext
from sein_zum_tode.payload_keys import UnsupportedUpdatePayloadKey
from sein_zum_tode.ports.documents import DocumentStore, DocumentWriter
from sein_zum_tode.unsupported.models import (
    PREPARE_UNSUPPORTED_ACTIVITY_NAME,
    UnsupportedResponsePreparation,
    UnsupportedUpdateContent,
    UnsupportedUpdateSession,
)


class PrepareUnsupportedResponseActivity:
    def __init__(
        self,
        *,
        sessions: DocumentStore[UnsupportedUpdateSession],
        responses: DocumentWriter[TelegramResponse],
        content: UnsupportedUpdateContent,
        bot_content: BotContent,
        mortals: MortalRepository,
        bot_id: int,
        session_ttl_seconds: int,
        response_ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sessions = sessions
        self._responses = responses
        self._content = content
        self._bot_content = bot_content
        self._mortals = mortals
        self._bot_id = bot_id
        self._session_ttl_seconds = session_ttl_seconds
        self._response_ttl_seconds = response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=PREPARE_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_unsupported(
        self,
        input: PrepareResponseInput,
    ) -> UnsupportedResponsePreparation:
        user_id = input.user_id if input.user_id is not None else input.chat_id
        session_key = UnsupportedUpdatePayloadKey(
            bot_id=self._bot_id,
            user_id=user_id,
        ).session()
        try:
            session = await self._sessions.load(session_key)
        except InvalidStoredPayloadError:
            session = None
        updated, response_text = (session or UnsupportedUpdateSession()).advance(
            update_key=input.update_key,
            content=self._content,
        )
        await self._sessions.store(
            session_key,
            updated,
            self._session_ttl_seconds,
        )
        if response_text is None and input.is_text_message:
            mortal = await self._mortals.get(user_id)
            locale = mortal.locale if mortal is not None else self._bot_content.default_locale
            response_text = self._bot_content.localized(locale).text_unsupported
        if response_text is not None:
            await self._responses.store(
                input.response_key,
                TelegramResponse(
                    chat_id=input.chat_id,
                    text=response_text,
                    callback_query_id=input.callback_query_id,
                ),
                self._response_ttl_seconds,
            )
        self._logger.info(
            "Unsupported Telegram update handled",
            extra=LogContext(
                component="worker",
                user_id=user_id,
                update_key=input.update_key,
            ).event(
                "unsupported_telegram_update_handled",
                response_prepared=response_text is not None,
            ),
        )
        return UnsupportedResponsePreparation(response_prepared=response_text is not None)
