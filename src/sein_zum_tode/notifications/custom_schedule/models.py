from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME = "generate_custom_notification_schedule"
APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME = "apply_custom_notification_schedule"
PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME = "prepare_custom_notification_failure"


class NotificationScheduleProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    understood: bool
    cron: str | None = Field(min_length=1, max_length=128)
    timezone: str = Field(min_length=1, max_length=64)
    explanation: str = Field(min_length=1, max_length=4096)

    def settings(self) -> NotificationScheduleSettings:
        return NotificationScheduleSettings(cron=self.cron, timezone=self.timezone)


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
                f"Required language for the explanation field: {self.locale}",
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
