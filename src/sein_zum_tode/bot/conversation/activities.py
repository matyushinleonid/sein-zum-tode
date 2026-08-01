import logging

from aiogram.enums import ChatType
from temporalio import activity

from sein_zum_tode.bot.content import TELEGRAM_TEXT_LIMIT, BotContent
from sein_zum_tode.bot.conversation.models import (
    RECORD_CONVERSATION_ANSWER_ACTIVITY_NAME,
    START_CONVERSATION_ACTIVITY_NAME,
    ConversationStarted,
    ConversationState,
    ConversationTurn,
    ConversationTurnKind,
    RecordConversationAnswerInput,
    StartConversationInput,
)
from sein_zum_tode.bot.conversation.ports import ConversationStateRepository
from sein_zum_tode.bot.errors import InvalidStoredPayloadError
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.ports import (
    TelegramResponseStore,
    TelegramUpdateReader,
)
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.observability import LogContext


class StartTelegramConversationActivity:
    def __init__(
        self,
        *,
        content: BotContent,
        mortals: MortalRepository,
        conversations: ConversationStateRepository,
        responses: TelegramResponseStore,
        conversation_ttl_seconds: int,
        response_ttl_seconds: int,
        privacy_response_ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._content = content
        self._mortals = mortals
        self._conversations = conversations
        self._responses = responses
        self._conversation_ttl_seconds = conversation_ttl_seconds
        self._response_ttl_seconds = response_ttl_seconds
        self._privacy_response_ttl_seconds = privacy_response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=START_CONVERSATION_ACTIVITY_NAME)
    async def start(self, input: StartConversationInput) -> ConversationStarted:
        mortal = await self._mortals.get(input.user_id)
        locale = (
            mortal.locale
            if mortal is not None and mortal.locale is not None
            else self._content.default_locale
        )
        state = ConversationState.begin(
            content=self._content,
            localized=self._content.localized(locale),
            locale=locale,
            user_id=input.user_id,
            chat_id=input.chat_id,
        )
        await self._conversations.store_conversation(
            input.conversation_key,
            state,
            self._conversation_ttl_seconds,
        )
        response_keys = tuple(
            f"{input.conversation_key}:initial:{index}"
            for index in range(len(state.initial_messages()))
        )
        for key, text in zip(response_keys, state.initial_messages(), strict=True):
            await self._responses.store_response(
                key,
                TelegramResponse(chat_id=input.chat_id, text=text),
                self._response_ttl_seconds,
            )
        privacy_response_key = f"{input.conversation_key}:privacy"
        await self._responses.store_response(
            privacy_response_key,
            TelegramResponse(chat_id=input.chat_id, text=state.deleted_message),
            self._privacy_response_ttl_seconds,
        )
        self._logger.info(
            "Telegram conversation started",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.conversation_key,
            ).event(
                "telegram_conversation_started",
                content_version=state.content_version,
                question_count=len(state.questions),
            ),
        )
        return ConversationStarted(
            response_keys=response_keys,
            privacy_response_key=privacy_response_key,
        )


class RecordTelegramConversationAnswerActivity:
    def __init__(
        self,
        *,
        updates: TelegramUpdateReader,
        conversations: ConversationStateRepository,
        responses: TelegramResponseStore,
        conversation_ttl_seconds: int,
        response_ttl_seconds: int,
        privacy_response_ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._updates = updates
        self._conversations = conversations
        self._responses = responses
        self._conversation_ttl_seconds = conversation_ttl_seconds
        self._response_ttl_seconds = response_ttl_seconds
        self._privacy_response_ttl_seconds = privacy_response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=RECORD_CONVERSATION_ANSWER_ACTIVITY_NAME)
    async def record(self, input: RecordConversationAnswerInput) -> ConversationTurn:
        try:
            state = await self._conversations.load_conversation(input.conversation_key)
        except InvalidStoredPayloadError:
            state = None
        if state is None:
            return ConversationTurn(kind=ConversationTurnKind.EXPIRED)

        try:
            update = await self._updates.load_update(input.update_key)
        except InvalidStoredPayloadError:
            update = None
        if (
            update is None
            or update.message is None
            or update.message.chat.type != ChatType.PRIVATE
            or update.message.text is None
        ):
            return ConversationTurn(kind=ConversationTurnKind.IGNORED)

        answer = state.apply_answer(
            update_key=input.update_key,
            text=update.message.text,
        )
        await self._conversations.store_conversation(
            input.conversation_key,
            answer.state,
            self._conversation_ttl_seconds,
        )
        response_keys = await self._store_response_parts(
            key_prefix=f"{input.update_key}:conversation-response",
            chat_id=state.chat_id,
            text=answer.response_text,
        )
        await self._responses.store_response(
            f"{input.conversation_key}:privacy",
            TelegramResponse(chat_id=state.chat_id, text=state.deleted_message),
            self._privacy_response_ttl_seconds,
        )
        kind = ConversationTurnKind.COMPLETED if answer.completed else ConversationTurnKind.QUESTION
        self._logger.info(
            "Telegram conversation answer recorded",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
            ).event(
                "telegram_conversation_answer_recorded",
                conversation_key=input.conversation_key,
                turn_kind=kind.value,
                question_index=answer.state.current_question_index,
            ),
        )
        return ConversationTurn(kind=kind, response_keys=response_keys)

    async def _store_response_parts(
        self,
        *,
        key_prefix: str,
        chat_id: int,
        text: str,
    ) -> tuple[str, ...]:
        parts = tuple(
            text[offset : offset + TELEGRAM_TEXT_LIMIT]
            for offset in range(0, len(text), TELEGRAM_TEXT_LIMIT)
        )
        keys = tuple(f"{key_prefix}:{index}" for index in range(len(parts)))
        for key, part in zip(keys, parts, strict=True):
            await self._responses.store_response(
                key,
                TelegramResponse(chat_id=chat_id, text=part),
                self._response_ttl_seconds,
            )
        return keys
