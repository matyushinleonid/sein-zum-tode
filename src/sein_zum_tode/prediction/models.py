from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class PredictionAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str
    question: str
    answer: str


class DeathPredictionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_date: date
    locale: str
    answers: tuple[PredictionAnswer, ...]

    def prompt(self) -> str:
        lines = [
            f"Current date: {self.current_date.isoformat()}",
            f"User locale: {self.locale}",
            "Questionnaire answers:",
        ]
        lines.extend(
            f"- {answer.question} ({answer.question_id}): {answer.answer}"
            for answer in self.answers
        )
        return "\n".join(lines)

    def answers_text(self) -> str:
        return ", ".join(f"{answer.question_id}-{answer.answer}" for answer in self.answers)


class DeathPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    days_left: int = Field(ge=0)
    message: str = Field(min_length=1)


class StoredDeathPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    provider: str
    consumes_quota: bool
    current_date: date
    prediction: DeathPrediction

    def death_date(self) -> date:
        return date.fromordinal(self.current_date.toordinal() + self.prediction.days_left)
