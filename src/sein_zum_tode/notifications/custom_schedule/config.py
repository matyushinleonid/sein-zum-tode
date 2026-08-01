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
from sein_zum_tode.notifications.custom_schedule.models import (
    CronOperation,
    TimezoneOperation,
)


class MockNotificationScheduleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cron_operation: CronOperation
    cron_expression: str | None = Field(default=None, min_length=1, max_length=128)
    timezone_operation: TimezoneOperation
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if (self.cron_operation == CronOperation.SET) != (self.cron_expression is not None):
            raise ValueError("mock cron_expression must be present exactly for the set operation")
        if (self.timezone_operation == TimezoneOperation.SET) != (self.timezone is not None):
            raise ValueError("mock timezone must be present exactly for the set operation")
        if (
            self.cron_operation == CronOperation.KEEP
            and self.timezone_operation == TimezoneOperation.KEEP
        ):
            raise ValueError("mock notification schedule must change a setting")
        return self


class NotificationScheduleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: CompletionProvider
    minimum_interval_hours: int = Field(default=20, ge=1)
    system_prompt: str = Field(min_length=1)
    mock: MockNotificationScheduleConfig
    yandex: YandexCompletionConfig
    openai: OpenAICompletionConfig


class NotificationScheduleConfigurationError(Exception):
    pass


class YamlNotificationScheduleConfigLoader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> NotificationScheduleConfig:
        try:
            payload = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            return NotificationScheduleConfig.model_validate(payload)
        except (OSError, YAMLError, ValidationError) as error:
            raise NotificationScheduleConfigurationError(
                f"Failed to load notification schedule config from {self._path}"
            ) from error
