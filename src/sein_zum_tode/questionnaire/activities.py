import logging

from aiogram.enums import ChatType
from aiogram.types import Update
from temporalio import activity

from sein_zum_tode.bot.content import TELEGRAM_TEXT_LIMIT, BotContent
from sein_zum_tode.bot.errors import InvalidStoredPayloadError
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.observability import LogContext
from sein_zum_tode.payload_keys import QuestionnairePayloadKeys
from sein_zum_tode.ports.documents import DocumentReader, DocumentStore, DocumentWriter
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics
from sein_zum_tode.questionnaire.models import (
    RECORD_QUESTIONNAIRE_ANSWER_ACTIVITY_NAME,
    START_QUESTIONNAIRE_ACTIVITY_NAME,
    QuestionnaireStarted,
    QuestionnaireState,
    QuestionnaireTurn,
    QuestionnaireTurnKind,
    RecordQuestionnaireAnswerInput,
    StartQuestionnaireInput,
)


class StartTelegramQuestionnaireActivity:
    def __init__(
        self,
        *,
        content: BotContent,
        mortals: MortalRepository,
        questionnaires: DocumentStore[QuestionnaireState],
        responses: DocumentWriter[TelegramResponse],
        questionnaire_ttl_seconds: int,
        response_ttl_seconds: int,
        privacy_response_ttl_seconds: int,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._content = content
        self._mortals = mortals
        self._questionnaires = questionnaires
        self._responses = responses
        self._questionnaire_ttl_seconds = questionnaire_ttl_seconds
        self._response_ttl_seconds = response_ttl_seconds
        self._privacy_response_ttl_seconds = privacy_response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=START_QUESTIONNAIRE_ACTIVITY_NAME)
    async def start(self, input: StartQuestionnaireInput) -> QuestionnaireStarted:
        mortal = await self._mortals.get(input.user_id)
        locale = (
            mortal.locale
            if mortal is not None and mortal.locale is not None
            else self._content.default_locale
        )
        state = QuestionnaireState.begin(
            content=self._content,
            localized=self._content.localized(locale),
            locale=locale,
            user_id=input.user_id,
            chat_id=input.chat_id,
        )
        await self._questionnaires.store(
            input.questionnaire_key,
            state,
            self._questionnaire_ttl_seconds,
        )
        response_keys = tuple(
            f"{input.questionnaire_key}:initial:{index}"
            for index in range(len(state.initial_messages()))
        )
        for key, text in zip(response_keys, state.initial_messages(), strict=True):
            await self._responses.store(
                key,
                TelegramResponse(chat_id=input.chat_id, text=text),
                self._response_ttl_seconds,
            )
        privacy_response_key = QuestionnairePayloadKeys(input.questionnaire_key).privacy_response()
        await self._responses.store(
            privacy_response_key,
            TelegramResponse(chat_id=input.chat_id, text=state.deleted_message),
            self._privacy_response_ttl_seconds,
        )
        self._logger.info(
            "Telegram questionnaire started",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                session_id=input.questionnaire_key,
            ).event(
                "telegram_questionnaire_started",
                content_version=state.content_version,
                question_count=len(state.questions),
            ),
        )
        self._metrics.questionnaire(event="started", locale=state.locale)
        return QuestionnaireStarted(
            response_keys=response_keys,
            privacy_response_key=privacy_response_key,
        )


class RecordTelegramQuestionnaireAnswerActivity:
    def __init__(
        self,
        *,
        updates: DocumentReader[Update],
        questionnaires: DocumentStore[QuestionnaireState],
        responses: DocumentWriter[TelegramResponse],
        questionnaire_ttl_seconds: int,
        response_ttl_seconds: int,
        privacy_response_ttl_seconds: int,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._updates = updates
        self._questionnaires = questionnaires
        self._responses = responses
        self._questionnaire_ttl_seconds = questionnaire_ttl_seconds
        self._response_ttl_seconds = response_ttl_seconds
        self._privacy_response_ttl_seconds = privacy_response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=RECORD_QUESTIONNAIRE_ANSWER_ACTIVITY_NAME)
    async def record(self, input: RecordQuestionnaireAnswerInput) -> QuestionnaireTurn:
        try:
            state = await self._questionnaires.load(input.questionnaire_key)
        except InvalidStoredPayloadError:
            state = None
        if state is None:
            self._metrics.questionnaire(event="expired", locale="unknown")
            return QuestionnaireTurn(kind=QuestionnaireTurnKind.EXPIRED)

        try:
            update = await self._updates.load(input.update_key)
        except InvalidStoredPayloadError:
            update = None
        if (
            update is None
            or update.message is None
            or update.message.chat.type != ChatType.PRIVATE
            or update.message.text is None
        ):
            self._metrics.questionnaire(event="ignored", locale=state.locale)
            return QuestionnaireTurn(kind=QuestionnaireTurnKind.IGNORED)

        answer = state.apply_answer(
            update_key=input.update_key,
            text=update.message.text,
        )
        await self._questionnaires.store(
            input.questionnaire_key,
            answer.state,
            self._questionnaire_ttl_seconds,
        )
        response_keys = await self._store_response_parts(
            key_prefix=f"{input.update_key}:questionnaire-response",
            chat_id=state.chat_id,
            text=answer.response_text,
        )
        await self._responses.store(
            QuestionnairePayloadKeys(input.questionnaire_key).privacy_response(),
            TelegramResponse(chat_id=state.chat_id, text=state.deleted_message),
            self._privacy_response_ttl_seconds,
        )
        kind = (
            QuestionnaireTurnKind.COMPLETED if answer.completed else QuestionnaireTurnKind.QUESTION
        )
        self._metrics.questionnaire(
            event=kind.value,
            locale=state.locale,
            question_index=state.current_question_index,
        )
        self._logger.info(
            "Telegram questionnaire answer recorded",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
                session_id=input.questionnaire_key,
            ).event(
                "telegram_questionnaire_answer_recorded",
                turn_kind=kind.value,
                question_index=answer.state.current_question_index,
            ),
        )
        return QuestionnaireTurn(kind=kind, response_keys=response_keys)

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
            await self._responses.store(
                key,
                TelegramResponse(chat_id=chat_id, text=part),
                self._response_ttl_seconds,
            )
        return keys
