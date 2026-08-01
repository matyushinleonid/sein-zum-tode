from pathlib import Path
from string import Formatter
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml import YAMLError

from sein_zum_tode.bot.errors import ContentConfigurationError

TELEGRAM_TEXT_LIMIT = 4096


class QuestionContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)


class QuestionnaireContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    started: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    completed: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    deleted: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    questions: tuple[QuestionContent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_question_ids(self) -> Self:
        ids = tuple(question.id for question in self.questions)
        if len(ids) != len(set(ids)):
            raise ValueError("questionnaire question IDs must be unique")
        return self


class NotificationSettingsContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    daily: str = Field(min_length=1, max_length=64)
    weekly: str = Field(min_length=1, max_length=64)
    monthly: str = Field(min_length=1, max_length=64)
    never: str = Field(min_length=1, max_length=64)
    updated: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)

    @model_validator(mode="after")
    def validate_updated_template(self) -> Self:
        fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.updated)
            if field_name is not None
        }
        if fields != {"frequency"}:
            raise ValueError("notification settings updated must contain {frequency}")
        return self

    def updated_text(self, frequency: str) -> str:
        return self.updated.format(frequency=frequency)


class LocalizationContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    russian: str = Field(min_length=1, max_length=64)
    english: str = Field(min_length=1, max_length=64)
    updated: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)


class PredictionContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    limit_exhausted: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    failed: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    mock: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)

    @model_validator(mode="after")
    def validate_mock_template(self) -> Self:
        fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.mock)
            if field_name is not None
        }
        if fields != {"answers"}:
            raise ValueError("prediction mock must contain only the {answers} placeholder")
        return self

    def mock_text(self, answers: str) -> str:
        return self.mock.format(answers=answers)


class LocalizedBotContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    help: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    about: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    unsupported: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    group_unsupported: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    notification: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    localization: LocalizationContent
    notification_settings: NotificationSettingsContent
    prediction: PredictionContent
    questionnaire: QuestionnaireContent

    @model_validator(mode="after")
    def validate_notification_template(self) -> Self:
        fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.notification)
            if field_name is not None
        }
        if fields != {"days_left"}:
            raise ValueError("notification must contain only the {days_left} placeholder")
        return self

    def notification_text(self, days_left: int) -> str:
        return self.notification.format(days_left=days_left)


class BotContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=128)
    default_locale: str = Field(min_length=2, max_length=16)
    locales: dict[str, LocalizedBotContent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_default_locale(self) -> Self:
        if self.default_locale not in self.locales:
            raise ValueError("default_locale must exist in locales")
        return self

    def default(self) -> LocalizedBotContent:
        return self.locales[self.default_locale]

    def localized(self, locale: str | None) -> LocalizedBotContent:
        if locale is None:
            return self.default()
        return self.locales.get(locale, self.default())


class YamlBotContentLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> BotContent:
        try:
            payload = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            return BotContent.model_validate(payload)
        except (OSError, YAMLError, ValidationError) as error:
            raise ContentConfigurationError(
                f"Failed to load bot content from {self._path}"
            ) from error
