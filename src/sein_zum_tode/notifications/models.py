from dataclasses import dataclass
from enum import StrEnum

MORTAL_NOTIFICATION_WORKFLOW_NAME = "MortalNotificationWorkflow"
PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME = "prepare_mortal_notification"
CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME = "configure_mortal_notifications"
CUSTOM_NOTIFICATION_CALLBACK_DATA = "notifications:custom"


class NotificationFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    NEVER = "never"

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


def is_custom_notification_callback(value: str | None) -> bool:
    return value == CUSTOM_NOTIFICATION_CALLBACK_DATA


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


@dataclass(frozen=True, slots=True)
class RenderedNotification:
    text: str
    parse_mode: str | None
    fallback_text: str | None
    variant_id: str | None
    decorated: bool
