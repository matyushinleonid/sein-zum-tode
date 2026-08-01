from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME = "generate_custom_notification_schedule"
APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME = "apply_custom_notification_schedule"
PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME = "prepare_custom_notification_failure"


class CronOperation(StrEnum):
    KEEP = "keep"
    SET = "set"
    DISABLE = "disable"


class TimezoneOperation(StrEnum):
    KEEP = "keep"
    SET = "set"


class CronChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CronOperation
    value: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        if (self.operation == CronOperation.SET) != (self.value is not None):
            raise ValueError("cron value must be present exactly for the set operation")
        return self


class TimezoneChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: TimezoneOperation
    value: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        if (self.operation == TimezoneOperation.SET) != (self.value is not None):
            raise ValueError("timezone value must be present exactly for the set operation")
        return self


class NotificationScheduleProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    understood: bool
    cron: CronChange
    timezone: TimezoneChange
    message: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_operations(self) -> Self:
        unchanged = (
            self.cron.operation == CronOperation.KEEP
            and self.timezone.operation == TimezoneOperation.KEEP
        )
        if self.understood == unchanged:
            raise ValueError(
                "understood proposals must change a setting and rejected proposals must not"
            )
        return self

    def resolve(
        self,
        *,
        current_cron: str | None,
        current_timezone: str,
    ) -> NotificationScheduleSettings:
        cron = current_cron
        if self.cron.operation == CronOperation.SET:
            cron = self.cron.value
        elif self.cron.operation == CronOperation.DISABLE:
            cron = None
        timezone = current_timezone
        if self.timezone.operation == TimezoneOperation.SET:
            timezone = self.timezone.value or current_timezone
        return NotificationScheduleSettings(cron=cron, timezone=timezone)


class NotificationScheduleRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    locale: str
    current_cron: str | None
    current_timezone: str
    current_local_datetime: datetime
    user_request: str = Field(min_length=1)

    def prompt(self) -> str:
        cron = self.current_cron if self.current_cron is not None else "disabled"
        return "\n".join(
            (
                f"Required language for the message field: {self.locale}",
                f"Current notification cron: {cron}",
                f"Current IANA timezone: {self.current_timezone}",
                (
                    "Current local datetime in that timezone: "
                    f"{self.current_local_datetime.isoformat()}"
                ),
                f"User request: {self.user_request}",
            )
        )


class NotificationScheduleSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cron: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str = Field(min_length=1, max_length=64)


class StoredNotificationScheduleProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    provider: str
    consumes_quota: bool
    proposal: NotificationScheduleProposal


@dataclass(frozen=True, slots=True)
class GenerateCustomNotificationScheduleInput:
    update_key: str
    proposal_key: str
    user_id: int


@dataclass(frozen=True, slots=True)
class ApplyCustomNotificationScheduleInput:
    proposal_key: str
    response_key: str
    user_id: int
    chat_id: int


@dataclass(frozen=True, slots=True)
class PrepareCustomNotificationFailureInput:
    response_key: str
    user_id: int
    chat_id: int
