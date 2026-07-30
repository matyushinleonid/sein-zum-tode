from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

TELEGRAM_USER_WORKFLOW_NAME = "TelegramUserWorkflow"
TELEGRAM_UPDATE_SIGNAL_NAME = "accept_update"
INSPECT_UPDATE_ACTIVITY_NAME = "inspect_telegram_update"
PREPARE_ECHO_ACTIVITY_NAME = "prepare_echo_response"
PREPARE_HELP_ACTIVITY_NAME = "prepare_help_response"
PREPARE_UNSUPPORTED_ACTIVITY_NAME = "prepare_unsupported_response"
PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME = "prepare_group_unsupported_response"
DELIVER_RESPONSE_ACTIVITY_NAME = "deliver_telegram_response"
CLEANUP_PAYLOADS_ACTIVITY_NAME = "cleanup_telegram_payloads"

UNSUPPORTED_RESPONSE_TEXT = "I cannot process this input."
GROUP_UNSUPPORTED_RESPONSE_TEXT = "Group chats are not supported. Please message me directly."


class InspectionKind(StrEnum):
    ECHO = "echo"
    HELP = "help"
    BEGIN = "begin"
    UNSUPPORTED = "unsupported"
    GROUP_UNSUPPORTED = "group_unsupported"


@dataclass(frozen=True, slots=True)
class UserWorkflowInput:
    user_id: int
    activity_retry_timeout_seconds: int
    conversation_ttl_seconds: int = 3600
    pending_update_keys: tuple[str, ...] = ()
    recent_update_keys: tuple[str, ...] = ()
    continue_as_new_after_updates: int | None = None


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

    def response_key(self) -> str:
        return f"{self.update_key}:response"


@dataclass(frozen=True, slots=True)
class PrepareResponseInput:
    update_key: str
    response_key: str
    chat_id: int
    user_id: int | None = None


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


class TelegramResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    chat_id: int
    text: str
