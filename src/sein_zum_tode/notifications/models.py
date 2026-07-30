from dataclasses import dataclass
from enum import StrEnum

MORTAL_NOTIFICATION_WORKFLOW_NAME = "MortalNotificationWorkflow"
PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME = "prepare_mortal_notification"
CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME = "configure_mortal_notifications"


class NotificationFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    NEVER = "never"

    def cron(self) -> str | None:
        return {
            NotificationFrequency.DAILY: "0 9 * * *",
            NotificationFrequency.WEEKLY: "0 9 * * 1",
            NotificationFrequency.MONTHLY: "0 9 1 * *",
            NotificationFrequency.NEVER: None,
        }[self]

    def callback_data(self) -> str:
        return f"notifications:{self.value}"

    @classmethod
    def from_callback_data(cls, value: str | None) -> NotificationFrequency | None:
        if value is None or not value.startswith("notifications:"):
            return None
        try:
            return cls(value.removeprefix("notifications:"))
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class MortalNotificationWorkflowInput:
    mortal_id: int
    activity_retry_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class PrepareMortalNotificationInput:
    mortal_id: int
    response_key: str


@dataclass(frozen=True, slots=True)
class PreparedMortalNotification:
    response_key: str
    days_left: int

    def terminal(self) -> bool:
        return self.days_left == 0
