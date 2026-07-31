from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yaml import YAMLError


class PredictionProvider(StrEnum):
    MOCK = "mock"
    YANDEX = "yandex"


class MockPredictionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    days_left: int = Field(ge=0)


class YandexPredictionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    temperature: float = Field(default=0.3, ge=0, le=1)
    max_tokens: int = Field(default=1000, ge=1)
    request_timeout_seconds: int = Field(default=180, ge=1)
    enable_server_data_logging: bool = False
    system_prompt: str = Field(min_length=1)


class DeathPredictionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: PredictionProvider
    mock: MockPredictionConfig
    yandex: YandexPredictionConfig


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
