from dataclasses import dataclass

TELEGRAM_SCREAM_WORKFLOW_NAME = "TelegramScreamWorkflow"
LIST_SCREAM_RECIPIENTS_ACTIVITY_NAME = "list_scream_recipients"
DELIVER_SCREAM_ACTIVITY_NAME = "deliver_scream"
PREPARE_SCREAM_REPORT_ACTIVITY_NAME = "prepare_scream_report"


@dataclass(frozen=True, slots=True)
class ScreamRequest:
    locale: str
    source_chat_id: int
    source_message_id: int


@dataclass(frozen=True, slots=True)
class ScreamWorkflowInput:
    request: ScreamRequest
    admin_user_id: int
    admin_chat_id: int
    update_key: str
    activity_retry_timeout_seconds: int
    recipient_page_size: int = 100


@dataclass(frozen=True, slots=True)
class ListScreamRecipientsInput:
    locale: str
    after_mortal_id: int | None
    limit: int
    admin_user_id: int
    update_key: str


@dataclass(frozen=True, slots=True)
class ScreamRecipients:
    mortal_ids: tuple[int, ...]

    def next_cursor(self) -> int | None:
        return self.mortal_ids[-1] if self.mortal_ids else None


@dataclass(frozen=True, slots=True)
class DeliverScreamInput:
    request: ScreamRequest
    recipient_id: int
    admin_user_id: int
    update_key: str


@dataclass(frozen=True, slots=True)
class PrepareScreamReportInput:
    response_key: str
    admin_chat_id: int
    admin_user_id: int
    update_key: str
    delivered: int
    failed: int

    def text(self) -> str:
        return f"Scream completed: {self.delivered} delivered, {self.failed} failed."
