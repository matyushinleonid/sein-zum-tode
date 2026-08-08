from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yaml import YAMLError

from sein_zum_tode.infrastructure.completion_config import (
    CompletionProvider,
    OpenAICompletionConfig,
    YandexCompletionConfig,
)


class MockPredictionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    days_left: int = Field(ge=0)


class DeathPredictionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: CompletionProvider
    fallback_provider: CompletionProvider | None = None
    system_prompt: str = Field(min_length=1)
    mock: MockPredictionConfig
    yandex: YandexCompletionConfig
    openai: OpenAICompletionConfig

    @model_validator(mode="after")
    def validate_fallback_provider(self) -> Self:
        if self.fallback_provider == self.provider:
            raise ValueError("fallback_provider must differ from provider")
        return self


class PredictionConfigurationError(Exception):
    pass


class YamlDeathPredictionConfigLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> DeathPredictionConfig:
        try:
            payload = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            return DeathPredictionConfig.model_validate(payload)
        except (OSError, YAMLError, ValidationError) as error:
            raise PredictionConfigurationError(
                f"Failed to load death prediction config from {self._path}"
            ) from error
