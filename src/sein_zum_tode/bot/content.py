from pathlib import Path
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


class ConversationContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    started: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    completed: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    deleted: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    questions: tuple[QuestionContent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_question_ids(self) -> Self:
        ids = tuple(question.id for question in self.questions)
        if len(ids) != len(set(ids)):
            raise ValueError("conversation question IDs must be unique")
        return self


class LocalizedBotContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    help: str = Field(min_length=1, max_length=TELEGRAM_TEXT_LIMIT)
    conversation: ConversationContent


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
