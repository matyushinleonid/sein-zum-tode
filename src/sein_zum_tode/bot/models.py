from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

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
PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME = "prepare_group_unsupported_response"
PREPARE_SCREAM_DENIED_ACTIVITY_NAME = "prepare_scream_denied_response"
DELIVER_RESPONSE_ACTIVITY_NAME = "deliver_telegram_response"
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
    UNSUPPORTED = "unsupported"
    GROUP_UNSUPPORTED = "group_unsupported"
    LIMIT_EXHAUSTED = "limit_exhausted"
    MORTAL_BLOCKED = "mortal_blocked"
    MORTAL_UNBLOCKED = "mortal_unblocked"


@dataclass(frozen=True, slots=True)
class UserWorkflowInput:
    user_id: int
    activity_retry_timeout_seconds: int
    questionnaire_ttl_seconds: int = 3600
    pending_update_keys: tuple[str, ...] = ()
    recent_update_keys: tuple[str, ...] = ()
    continue_as_new_after_updates: int | None = None
    awaiting_custom_notification: bool = False


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

    def response_key(self) -> str:
        return UpdatePayloadKeys(self.update_key).response()


@dataclass(frozen=True, slots=True)
class PrepareResponseInput:
    update_key: str
    response_key: str
    chat_id: int
    user_id: int | None = None
    callback_query_id: str | None = None


@dataclass(frozen=True, slots=True)
class DeliverResponseInput:
    response_key: str
    update_key: str | None = None
    user_id: int | None = None


@dataclass(frozen=True, slots=True)
class CleanupPayloadsInput:
    keys: tuple[str, ...]
    update_key: str | None = None
    user_id: int | None = None


class TelegramButton(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    callback_data: str


class TelegramResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    chat_id: int
    text: str
    parse_mode: str | None = None
    fallback_text: str | None = None
    keyboard: tuple[tuple[TelegramButton, ...], ...] = ()
    callback_query_id: str | None = None
