from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompletionProvider(StrEnum):
    MOCK = "mock"
    YANDEX = "yandex"
    OPENAI = "openai"


class YandexCompletionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    temperature: float = Field(default=0.3, ge=0, le=1)
    max_tokens: int = Field(default=1000, ge=1)
    request_timeout_seconds: int = Field(default=120, ge=1)


class OpenAICompletionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1)
    reasoning_effort: Literal[
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ] = "medium"
    max_output_tokens: int = Field(default=1000, ge=1)
    request_timeout_seconds: int = Field(default=120, ge=1)
