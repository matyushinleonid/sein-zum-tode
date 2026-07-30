from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from sein_zum_tode.bot.content import BotContent, LocalizedBotContent

TELEGRAM_CONVERSATION_WORKFLOW_NAME = "TelegramConversationWorkflow"
CONVERSATION_UPDATE_SIGNAL_NAME = "accept_conversation_update"
CONVERSATION_FINISHED_SIGNAL_NAME = "conversation_finished"
START_CONVERSATION_ACTIVITY_NAME = "start_telegram_conversation"
RECORD_CONVERSATION_ANSWER_ACTIVITY_NAME = "record_telegram_conversation_answer"


class ConversationQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    answer: str | None = None
    answer_update_key: str | None = None

    def answered(self, answer: str, update_key: str) -> ConversationQuestion:
        return self.model_copy(
            update={
                "answer": answer,
                "answer_update_key": update_key,
            }
        )


class ConversationState(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    content_version: str
    locale: str
    user_id: int
    chat_id: int
    started_message: str
    completed_message: str
    deleted_message: str
    questions: tuple[ConversationQuestion, ...]
    current_question_index: int = 0

    @classmethod
    def begin(
        cls,
        *,
        content: BotContent,
        localized: LocalizedBotContent,
        user_id: int,
        chat_id: int,
    ) -> ConversationState:
        conversation = localized.conversation
        return cls(
            content_version=content.version,
            locale=content.default_locale,
            user_id=user_id,
            chat_id=chat_id,
            started_message=conversation.started,
            completed_message=conversation.completed,
            deleted_message=conversation.deleted,
            questions=tuple(
                ConversationQuestion(id=question.id, text=question.text)
                for question in conversation.questions
            ),
        )

    def initial_messages(self) -> tuple[str, str]:
        return self.started_message, self.questions[0].text

    def apply_answer(self, *, update_key: str, text: str) -> AppliedConversationAnswer:
        existing_index = self._answer_index(update_key)
        if existing_index is not None:
            return AppliedConversationAnswer(
                state=self,
                response_text=self._response_after(existing_index),
                completed=existing_index == len(self.questions) - 1,
            )

        question_index = self.current_question_index
        if question_index >= len(self.questions):
            return AppliedConversationAnswer(
                state=self,
                response_text=self.summary(),
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
        return AppliedConversationAnswer(
            state=state,
            response_text=state._response_after(question_index),
            completed=question_index == len(questions) - 1,
        )

    def summary(self) -> str:
        answers = [
            {
                "question_id": question.id,
                "question": question.text,
                "answer": question.answer,
            }
            for question in self.questions
        ]
        return f"{self.completed_message} {answers}"

    def _answer_index(self, update_key: str) -> int | None:
        for index, question in enumerate(self.questions):
            if question.answer_update_key == update_key:
                return index
        return None

    def _response_after(self, answered_index: int) -> str:
        next_index = answered_index + 1
        if next_index < len(self.questions):
            return self.questions[next_index].text
        return self.summary()


@dataclass(frozen=True, slots=True)
class AppliedConversationAnswer:
    state: ConversationState
    response_text: str
    completed: bool


@dataclass(frozen=True, slots=True)
class ConversationWorkflowInput:
    conversation_key: str
    user_id: int
    chat_id: int
    inactivity_timeout_seconds: int
    activity_retry_timeout_seconds: int
    owner_workflow_id: str = ""


@dataclass(frozen=True, slots=True)
class ConversationUpdateSignal:
    update_key: str


@dataclass(frozen=True, slots=True)
class ConversationFinishedSignal:
    conversation_key: str


@dataclass(frozen=True, slots=True)
class StartConversationInput:
    conversation_key: str
    user_id: int
    chat_id: int


@dataclass(frozen=True, slots=True)
class ConversationStarted:
    response_keys: tuple[str, ...]
    privacy_response_key: str


@dataclass(frozen=True, slots=True)
class RecordConversationAnswerInput:
    conversation_key: str
    update_key: str
    user_id: int


class ConversationTurnKind(StrEnum):
    QUESTION = "question"
    COMPLETED = "completed"
    IGNORED = "ignored"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    kind: ConversationTurnKind
    response_keys: tuple[str, ...] = ()

    def accepted(self) -> bool:
        return self.kind in {
            ConversationTurnKind.QUESTION,
            ConversationTurnKind.COMPLETED,
        }

    def completed(self) -> bool:
        return self.kind == ConversationTurnKind.COMPLETED
