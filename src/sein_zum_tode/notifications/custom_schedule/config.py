from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    NotificationScheduleSettings,
    TimezoneOperation,
)
from sein_zum_tode.notifications.custom_schedule.validation import (
    NotificationScheduleValidator,
)
from sein_zum_tode.notifications.models import NotificationFrequency


class NotificationPresets(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily: str = Field(min_length=1, max_length=128)
    weekly: str = Field(min_length=1, max_length=128)
    monthly: str = Field(min_length=1, max_length=128)
    never: None = None

    def cron(self, frequency: NotificationFrequency) -> str | None:
        return {
            NotificationFrequency.DAILY: self.daily,
            NotificationFrequency.WEEKLY: self.weekly,
            NotificationFrequency.MONTHLY: self.monthly,
            NotificationFrequency.NEVER: self.never,
        }[frequency]


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

    default_timezone: str = Field(min_length=1, max_length=64)
    default_frequency: NotificationFrequency
    presets: NotificationPresets
    provider: CompletionProvider
    minimum_interval_hours: int = Field(default=20, ge=1)
    system_prompt: str = Field(min_length=1)
    mock: MockNotificationScheduleConfig
    yandex: YandexCompletionConfig
    openai: OpenAICompletionConfig

    @model_validator(mode="after")
    def validate_default_timezone(self) -> Self:
        try:
            ZoneInfo(self.default_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("default_timezone must be a valid IANA timezone") from error
        validator = NotificationScheduleValidator(
            minimum_interval=timedelta(hours=self.minimum_interval_hours)
        )
        for frequency in NotificationFrequency:
            validator.validate(
                NotificationScheduleSettings(
                    cron=self.presets.cron(frequency),
                    timezone=self.default_timezone,
                ),
                now=datetime(2026, 1, 1, tzinfo=UTC),
            )
        return self

    def default_cron(self) -> str | None:
        return self.presets.cron(self.default_frequency)


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
