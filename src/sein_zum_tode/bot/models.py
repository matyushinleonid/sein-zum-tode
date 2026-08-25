from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from sein_zum_tode.bot.content import NotificationTier
from sein_zum_tode.broadcasts.models import ScreamRequest
from sein_zum_tode.payload_keys import UpdatePayloadKeys

TELEGRAM_USER_WORKFLOW_NAME = "TelegramUserWorkflow"
TELEGRAM_UPDATE_SIGNAL_NAME = "accept_update"
INSPECT_UPDATE_ACTIVITY_NAME = "inspect_telegram_update"
PREPARE_HELP_ACTIVITY_NAME = "prepare_help_response"
PREPARE_ABOUT_ACTIVITY_NAME = "prepare_about_response"
PREPARE_LOCALIZATION_ACTIVITY_NAME = "prepare_localization_response"
PREPARE_NOTIFICATIONS_ACTIVITY_NAME = "prepare_notifications_response"
PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME = "prepare_custom_notification_response"
PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME = "prepare_limit_exhausted_response"
PREPARE_PAYLOAD_EXPIRED_ACTIVITY_NAME = "prepare_payload_expired_response"
PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME = "prepare_group_unsupported_response"
PREPARE_SCREAM_DENIED_ACTIVITY_NAME = "prepare_scream_denied_response"
DELIVER_RESPONSE_ACTIVITY_NAME = "deliver_telegram_response"
DELIVER_NOTIFICATION_RESPONSE_ACTIVITY_NAME = "deliver_notification_response"
CLEANUP_PAYLOADS_ACTIVITY_NAME = "cleanup_telegram_payloads"


class InspectionKind(StrEnum):
    TEXT = "text"
    HELP = "help"
    ABOUT = "about"
    LOCALIZATION = "localization"
    LOCALIZATION_SELECTION = "localization_selection"
    NOTIFICATIONS = "notifications"
    NOTIFICATION_SELECTION = "notification_selection"
    CUSTOM_NOTIFICATION_SELECTION = "custom_notification_selection"
    BEGIN = "begin"
    SCREAM = "scream"
    SCREAM_DENIED = "scream_denied"
    SCREAM_UNSUPPORTED = "scream_unsupported"
    NOTIFICATION_SAMPLE = "notification_sample"
    UNKNOWN_COMMAND = "unknown_command"
    UNSUPPORTED = "unsupported"
    GROUP_UNSUPPORTED = "group_unsupported"
    LIMIT_EXHAUSTED = "limit_exhausted"
    PAYLOAD_EXPIRED = "payload_expired"
    MORTAL_BLOCKED = "mortal_blocked"
    MORTAL_UNBLOCKED = "mortal_unblocked"


class DeliveryKind(StrEnum):
    RESPONSE = "response"
    QUESTIONNAIRE = "questionnaire"
    NOTIFICATION = "notification"
    BROADCAST_REPORT = "broadcast_report"


class PreparedResponseDeliveryOutcome(StrEnum):
    DELIVERED = "delivered"
    RESPONSE_EXPIRED = "response_expired"


class PayloadKind(StrEnum):
    UPDATE = "update"
    QUESTIONNAIRE = "questionnaire"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"
    CUSTOM_SCHEDULE = "custom_schedule"


class TelegramKeyboardMode(StrEnum):
    INLINE = "inline"
    REPLY = "reply"


@dataclass(frozen=True, slots=True)
class UserWorkflowInput:
    user_id: int
    activity_retry_timeout_seconds: int
    questionnaire_ttl_seconds: int = 3600
    pending_update_keys: tuple[str, ...] = ()
    recent_update_keys: tuple[str, ...] = ()
    continue_as_new_after_updates: int | None = None
    awaiting_custom_notification: bool = False
    broadcast_recipient_page_size: int = 100


@dataclass(frozen=True, slots=True)
class TelegramUpdateSignal:
    redis_key: str


@dataclass(frozen=True, slots=True)
class InspectUpdateInput:
    update_key: str
    user_id: int


@dataclass(frozen=True, slots=True)
class InspectedUpdate:
    kind: InspectionKind
    update_key: str
    chat_id: int
    callback_query_id: str | None = None
    scream_request: ScreamRequest | None = None
    notification_sample: NotificationTier | None = None
    reply_keyboard_selection: bool = False

    def response_key(self) -> str:
        return UpdatePayloadKeys(self.update_key).response()


@dataclass(frozen=True, slots=True)
class PrepareResponseInput:
    update_key: str
    response_key: str
    chat_id: int
    user_id: int | None = None
    callback_query_id: str | None = None
    is_text_message: bool = False
    notification_sample: NotificationTier | None = None
    remove_reply_keyboard: bool = False


@dataclass(frozen=True, slots=True)
class DeliverResponseInput:
    response_key: str
    update_key: str | None = None
    user_id: int | None = None
    delivery_kind: DeliveryKind = DeliveryKind.RESPONSE


@dataclass(frozen=True, slots=True)
class CleanupPayloadsInput:
    keys: tuple[str, ...]
    update_key: str | None = None
    user_id: int | None = None
    payload_kind: PayloadKind = PayloadKind.UPDATE


class TelegramButton(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    callback_data: str


class TelegramAttachmentKind(StrEnum):
    AUDIO = "audio"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"


class TelegramAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: TelegramAttachmentKind
    url: str


class TelegramResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    chat_id: int
    text: str
    parse_mode: str | None = None
    fallback_text: str | None = None
    prelude_text: str | None = None
    attachment: TelegramAttachment | None = None
    keyboard: tuple[tuple[TelegramButton, ...], ...] = ()
    keyboard_mode: TelegramKeyboardMode = TelegramKeyboardMode.INLINE
    remove_reply_keyboard: bool = False
    callback_query_id: str | None = None

    @model_validator(mode="after")
    def validate_keyboard(self) -> TelegramResponse:
        if self.keyboard and self.remove_reply_keyboard:
            raise ValueError("Telegram response cannot show and remove a keyboard together")
        return self
