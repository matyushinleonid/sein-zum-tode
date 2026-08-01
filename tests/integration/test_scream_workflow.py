from collections.abc import Callable, Sequence
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
)
from sein_zum_tode.broadcasts.models import (
    DELIVER_SCREAM_ACTIVITY_NAME,
    LIST_SCREAM_RECIPIENTS_ACTIVITY_NAME,
    PREPARE_SCREAM_REPORT_ACTIVITY_NAME,
    TELEGRAM_SCREAM_WORKFLOW_NAME,
    DeliverScreamInput,
    ListScreamRecipientsInput,
    PrepareScreamReportInput,
    ScreamRecipients,
    ScreamRequest,
    ScreamWorkflowInput,
)
from sein_zum_tode.broadcasts.workflow import TelegramScreamWorkflow
from sein_zum_tode.mortals.activities import (
    DEACTIVATE_MORTAL_ACTIVITY_NAME,
    MortalActivityInput,
)

pytestmark = [
    pytest.mark.deep,
    pytest.mark.asyncio(loop_scope="module"),
]


def result_or_raise[T](outcome: T | BaseException) -> T:
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome


class ScreamTranscript:
    def __init__(
        self,
        *,
        pages: dict[int | None, ScreamRecipients | BaseException],
        deliveries: dict[int, BaseException] | None = None,
        deactivations: Sequence[BaseException | None] = (),
        report_delivery: BaseException | None = None,
        cleanup: BaseException | None = None,
    ) -> None:
        self.pages = pages
        self.deliveries = dict(deliveries or {})
        self.deactivations = list(deactivations)
        self.report_delivery = report_delivery
        self.cleanup_outcome = cleanup
        self.events: list[tuple[object, ...]] = []

    @activity.defn(name=LIST_SCREAM_RECIPIENTS_ACTIVITY_NAME)
    async def list_recipients(self, input: ListScreamRecipientsInput) -> ScreamRecipients:
        self.events.append(("list", input.locale, input.after_mortal_id, input.limit))
        return result_or_raise(self.pages[input.after_mortal_id])

    @activity.defn(name=DELIVER_SCREAM_ACTIVITY_NAME)
    async def deliver_scream(self, input: DeliverScreamInput) -> None:
        self.events.append(
            (
                "copy",
                input.recipient_id,
                input.request.source_chat_id,
                input.request.source_message_id,
            )
        )
        result_or_raise(self.deliveries.get(input.recipient_id))

    @activity.defn(name=DEACTIVATE_MORTAL_ACTIVITY_NAME)
    async def deactivate(self, input: MortalActivityInput) -> None:
        self.events.append(("deactivate", input.mortal_id))
        outcome = self.deactivations.pop(0) if self.deactivations else None
        result_or_raise(outcome)

    @activity.defn(name=PREPARE_SCREAM_REPORT_ACTIVITY_NAME)
    async def prepare_report(self, input: PrepareScreamReportInput) -> None:
        self.events.append(("report", input.delivered, input.failed, input.text()))

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver_report(self, input: DeliverResponseInput) -> None:
        self.events.append(("deliver_report", input.response_key, input.user_id))
        result_or_raise(self.report_delivery)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        self.events.append(("cleanup", input.keys, input.user_id))
        result_or_raise(self.cleanup_outcome)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.list_recipients,
            self.deliver_scream,
            self.deactivate,
            self.prepare_report,
            self.deliver_report,
            self.cleanup,
        ]


def workflow_input() -> ScreamWorkflowInput:
    return ScreamWorkflowInput(
        request=ScreamRequest(
            locale="ru",
            source_chat_id=162573173,
            source_message_id=190_019,
        ),
        admin_user_id=162573173,
        admin_chat_id=162573173,
        update_key="telegram:updates:1901",
        activity_retry_timeout_seconds=1,
        recipient_page_size=2,
    )


async def execute(
    environment: WorkflowEnvironment,
    transcript: ScreamTranscript,
) -> None:
    task_queue = f"scream-tests-{uuid4()}"
    async with Worker(
        environment.client,
        task_queue=task_queue,
        workflows=[TelegramScreamWorkflow],
        activities=transcript.definitions(),
    ):
        await environment.client.execute_workflow(
            TELEGRAM_SCREAM_WORKFLOW_NAME,
            workflow_input(),
            id=f"scream-test-{uuid4()}",
            task_queue=task_queue,
        )


async def test_pages_recipients_delivers_each_message_and_reports_totals(
    temporal_environment: WorkflowEnvironment,
) -> None:
    transcript = ScreamTranscript(
        pages={
            None: ScreamRecipients(mortal_ids=(190_027, 190_031)),
            190_031: ScreamRecipients(mortal_ids=(190_037,)),
        }
    )

    await execute(temporal_environment, transcript)

    assert transcript.events == [
        ("list", "ru", None, 2),
        ("copy", 190_027, 162573173, 190_019),
        ("copy", 190_031, 162573173, 190_019),
        ("list", "ru", 190_031, 2),
        ("copy", 190_037, 162573173, 190_019),
        (
            "report",
            3,
            0,
            "Scream completed: 3 delivered, 0 failed.",
        ),
        ("deliver_report", "telegram:updates:1901:scream-report", 162573173),
        (
            "cleanup",
            (
                "telegram:updates:1901",
                "telegram:updates:1901:scream-report",
            ),
            162573173,
        ),
    ], "scream workflow skipped a page, recipient, report, or Redis cleanup"


async def test_counts_failures_and_deactivates_only_blocked_recipients(
    temporal_environment: WorkflowEnvironment,
) -> None:
    blocked = ApplicationError(
        "recipient blocked bot",
        type="TelegramRecipientUnavailable",
        non_retryable=True,
    )
    transcript = ScreamTranscript(
        pages={
            None: ScreamRecipients(mortal_ids=(190_043, 190_051)),
            190_051: ScreamRecipients(mortal_ids=(190_057,)),
        },
        deliveries={
            190_043: blocked,
            190_051: blocked,
            190_057: ApplicationError(
                "copy rejected",
                type="PermanentTelegramDeliveryError",
                non_retryable=True,
            ),
        },
        deactivations=(
            None,
            ApplicationError("PostgreSQL unavailable", non_retryable=True),
        ),
        report_delivery=ApplicationError("admin unavailable", non_retryable=True),
        cleanup=ApplicationError("Redis unavailable", non_retryable=True),
    )

    await execute(temporal_environment, transcript)

    assert (
        [event for event in transcript.events if event[0] == "deactivate"],
        [event for event in transcript.events if event[0] == "report"],
        transcript.events[-1][0],
    ) == (
        [("deactivate", 190_043), ("deactivate", 190_051)],
        [("report", 0, 3, "Scream completed: 0 delivered, 3 failed.")],
        "cleanup",
    ), "blocked recipients, permanent failures, or best-effort cleanup were misclassified"


async def test_reports_an_empty_partial_result_when_recipient_selection_fails(
    temporal_environment: WorkflowEnvironment,
) -> None:
    transcript = ScreamTranscript(
        pages={
            None: ApplicationError(
                "PostgreSQL unavailable",
                non_retryable=True,
            )
        }
    )

    await execute(temporal_environment, transcript)

    assert transcript.events[1:3] == [
        ("report", 0, 0, "Scream completed: 0 delivered, 0 failed."),
        ("deliver_report", "telegram:updates:1901:scream-report", 162573173),
    ], "recipient selection failure suppressed the admin report"
