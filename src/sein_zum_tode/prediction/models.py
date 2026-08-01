from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    prediction_possible: bool
    days_left: int | None = Field(default=None, ge=0)
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_days_left(self) -> Self:
        if self.prediction_possible != (self.days_left is not None):
            raise ValueError("days_left must be present exactly when prediction_possible is true")
        return self


class StoredDeathPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    provider: str
    consumes_quota: bool
    current_date: date
    prediction: DeathPrediction

    def death_date(self) -> date | None:
        if self.prediction.days_left is None:
            return None
        return date.fromordinal(self.current_date.toordinal() + self.prediction.days_left)
