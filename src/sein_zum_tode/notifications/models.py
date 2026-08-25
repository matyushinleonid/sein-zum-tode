from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from sein_zum_tode.bot.content import NotificationTier
from sein_zum_tode.bot.models import TelegramAttachment

MORTAL_NOTIFICATION_WORKFLOW_NAME = "MortalNotificationWorkflow"
PLAN_MORTAL_NOTIFICATION_DELIVERY_ACTIVITY_NAME = "plan_mortal_notification_delivery"
PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME = "prepare_mortal_notification"
PREPARE_NOTIFICATION_SAMPLE_ACTIVITY_NAME = "prepare_notification_sample"
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
    delivery_deadline: str | None = None

    def parsed_delivery_deadline(self) -> datetime | None:
        if self.delivery_deadline is None:
            return None
        return datetime.fromisoformat(self.delivery_deadline)

    def with_delivery_deadline(self, deadline: datetime) -> MortalNotificationWorkflowInput:
        return replace(self, delivery_deadline=deadline.isoformat())


@dataclass(frozen=True, slots=True)
class PlanMortalNotificationDeliveryInput:
    mortal_id: int


@dataclass(frozen=True, slots=True)
class MortalNotificationDeliveryPlan:
    delivery_deadline: str

    @classmethod
    def ending_at(cls, deadline: datetime) -> MortalNotificationDeliveryPlan:
        return cls(delivery_deadline=deadline.isoformat())

    def parsed_delivery_deadline(self) -> datetime:
        return datetime.fromisoformat(self.delivery_deadline)


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
    prelude_text: str | None
    attachment: TelegramAttachment | None
    variant_id: str | None
    tier: NotificationTier | None
