from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from sein_zum_tode.bot.content import BotContent, LocalizedBotContent
from sein_zum_tode.prediction.models import PredictionAnswer

TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME = "TelegramQuestionnaireWorkflow"
QUESTIONNAIRE_UPDATE_SIGNAL_NAME = "accept_questionnaire_update"
QUESTIONNAIRE_FINISHED_SIGNAL_NAME = "questionnaire_finished"
START_QUESTIONNAIRE_ACTIVITY_NAME = "start_telegram_questionnaire"
RECORD_QUESTIONNAIRE_ANSWER_ACTIVITY_NAME = "record_telegram_questionnaire_answer"


class QuestionnaireQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    answer: str | None = None
    answer_update_key: str | None = None

    def answered(self, answer: str, update_key: str) -> QuestionnaireQuestion:
        return self.model_copy(
            update={
                "answer": answer,
                "answer_update_key": update_key,
            }
        )


class QuestionnaireState(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 2
    content_version: str
    locale: str
    user_id: int
    chat_id: int
    privacy_notice_message: str
    started_message: str
    completed_message: str
    deleted_message: str
    cleanup_failed_message: str
    questions: tuple[QuestionnaireQuestion, ...]
    current_question_index: int = 0

    @classmethod
    def begin(
        cls,
        *,
        content: BotContent,
        localized: LocalizedBotContent,
        locale: str,
        user_id: int,
        chat_id: int,
    ) -> QuestionnaireState:
        questionnaire = localized.questionnaire
        return cls(
            content_version=content.version,
            locale=locale,
            user_id=user_id,
            chat_id=chat_id,
            privacy_notice_message=questionnaire.privacy_notice,
            started_message=questionnaire.started,
            completed_message=questionnaire.completed,
            deleted_message=questionnaire.deleted,
            cleanup_failed_message=questionnaire.cleanup_failed,
            questions=tuple(
                QuestionnaireQuestion(id=question.id, text=question.text)
                for question in questionnaire.questions
            ),
        )

    def initial_messages(self) -> tuple[str, ...]:
        return self.privacy_notice_message, self.started_message, self.questions[0].text

    def apply_answer(self, *, update_key: str, text: str) -> AppliedQuestionnaireAnswer:
        existing_index = self._answer_index(update_key)
        if existing_index is not None:
            return AppliedQuestionnaireAnswer(
                state=self,
                response_text=self._response_after(existing_index),
                completed=existing_index == len(self.questions) - 1,
            )

        question_index = self.current_question_index
        if question_index >= len(self.questions):
            return AppliedQuestionnaireAnswer(
                state=self,
                response_text=self.completed_message,
                completed=True,
            )

        questions = list(self.questions)
        questions[question_index] = questions[question_index].answered(text, update_key)
        state = self.model_copy(
            update={
                "questions": tuple(questions),
                "current_question_index": question_index + 1,
            }
        )
        return AppliedQuestionnaireAnswer(
            state=state,
            response_text=state._response_after(question_index),
            completed=question_index == len(questions) - 1,
        )

    def prediction_answers(self) -> tuple[PredictionAnswer, ...]:
        return tuple(
            PredictionAnswer(
                question_id=question.id,
                question=question.text,
                answer=question.answer,
            )
            for question in self.questions
            if question.answer is not None
        )

    def _answer_index(self, update_key: str) -> int | None:
        for index, question in enumerate(self.questions):
            if question.answer_update_key == update_key:
                return index
        return None

    def _response_after(self, answered_index: int) -> str:
        next_index = answered_index + 1
        if next_index < len(self.questions):
            return self.questions[next_index].text
        return self.completed_message


@dataclass(frozen=True, slots=True)
class AppliedQuestionnaireAnswer:
    state: QuestionnaireState
    response_text: str
    completed: bool


@dataclass(frozen=True, slots=True)
class QuestionnaireWorkflowInput:
    questionnaire_key: str
    user_id: int
    chat_id: int
    inactivity_timeout_seconds: int
    activity_retry_timeout_seconds: int
    owner_workflow_id: str = ""


@dataclass(frozen=True, slots=True)
class QuestionnaireUpdateSignal:
    update_key: str


@dataclass(frozen=True, slots=True)
class QuestionnaireFinishedSignal:
    questionnaire_key: str


@dataclass(frozen=True, slots=True)
class StartQuestionnaireInput:
    questionnaire_key: str
    user_id: int
    chat_id: int


@dataclass(frozen=True, slots=True)
class QuestionnaireStarted:
    response_keys: tuple[str, ...]
    privacy_response_key: str
    cleanup_failure_response_key: str


@dataclass(frozen=True, slots=True)
class RecordQuestionnaireAnswerInput:
    questionnaire_key: str
    update_key: str
    user_id: int


class QuestionnaireTurnKind(StrEnum):
    QUESTION = "question"
    COMPLETED = "completed"
    IGNORED = "ignored"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class QuestionnaireTurn:
    kind: QuestionnaireTurnKind
    response_keys: tuple[str, ...] = ()

    def accepted(self) -> bool:
        return self.kind in {
            QuestionnaireTurnKind.QUESTION,
            QuestionnaireTurnKind.COMPLETED,
        }

    def completed(self) -> bool:
        return self.kind == QuestionnaireTurnKind.COMPLETED
