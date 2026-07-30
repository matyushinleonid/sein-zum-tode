from collections.abc import Callable, Sequence
from types import TracebackType
from typing import cast
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
)
from sein_zum_tode.mortals.activities import (
    DEACTIVATE_MORTAL_ACTIVITY_NAME,
    DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
    MortalActivityInput,
)
from sein_zum_tode.notifications.models import (
    MORTAL_NOTIFICATION_WORKFLOW_NAME,
    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
    MortalNotificationWorkflowInput,
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
)
from sein_zum_tode.notifications.workflow import MortalNotificationWorkflow

pytestmark = pytest.mark.deep


def result_or_raise(value: object) -> object:
    if isinstance(value, BaseException):
        raise value
    return value


class NotificationActivityTranscript:
    def __init__(
        self,
        *,
        prepare_outcome: object,
        delivery_outcome: object = None,
        cleanup_outcome: object = None,
        deactivate_outcome: object = None,
        delete_schedule_outcome: object = None,
    ) -> None:
        self.prepare_outcome = prepare_outcome
        self.delivery_outcome = delivery_outcome
        self.cleanup_outcome = cleanup_outcome
        self.deactivate_outcome = deactivate_outcome
        self.delete_schedule_outcome = delete_schedule_outcome
        self.events: list[tuple[object, ...]] = []

    @activity.defn(name=PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME)
    async def prepare(
        self,
        input: PrepareMortalNotificationInput,
    ) -> PreparedMortalNotification | None:
        self.events.append(("prepare", input.mortal_id, input.response_key))
        return cast(
            PreparedMortalNotification | None,
            result_or_raise(self.prepare_outcome),
        )

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        self.events.append(("deliver", input.user_id, input.response_key))
        result_or_raise(self.delivery_outcome)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        self.events.append(("cleanup", input.user_id, input.keys))
        result_or_raise(self.cleanup_outcome)

    @activity.defn(name=DEACTIVATE_MORTAL_ACTIVITY_NAME)
    async def deactivate(self, input: MortalActivityInput) -> None:
        self.events.append(("deactivate", input.mortal_id))
        result_or_raise(self.deactivate_outcome)

    @activity.defn(name=DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME)
    async def delete_schedule(self, input: MortalActivityInput) -> None:
        self.events.append(("delete_schedule", input.mortal_id))
        result_or_raise(self.delete_schedule_outcome)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.prepare,
            self.deliver,
            self.cleanup,
            self.deactivate,
            self.delete_schedule,
        ]


class NotificationWorkflowStory:
    def __init__(
        self,
        *,
        environment: WorkflowEnvironment,
        worker: Worker,
        task_queue: str,
    ) -> None:
        self.environment = environment
        self.worker = worker
        self.task_queue = task_queue

    @classmethod
    async def open(
        cls,
        activities: Sequence[Callable[..., object]],
    ) -> NotificationWorkflowStory:
        environment = await WorkflowEnvironment.start_time_skipping()
        task_queue = f"deep-notification-{uuid4()}"
        worker = Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[MortalNotificationWorkflow],
            activities=activities,
        )
        await worker.__aenter__()
        return cls(
            environment=environment,
            worker=worker,
            task_queue=task_queue,
        )

    async def __aenter__(self) -> NotificationWorkflowStory:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.worker.__aexit__(exception_type, exception, traceback)
        await self.environment.shutdown()

    async def run(self) -> None:
        await self.environment.client.execute_workflow(
            MORTAL_NOTIFICATION_WORKFLOW_NAME,
            MortalNotificationWorkflowInput(
                mortal_id=360_007,
                activity_retry_timeout_seconds=7,
            ),
            id=f"deep-notification-{uuid4()}",
            task_queue=self.task_queue,
        )


async def test_delivers_and_cleans_a_nonterminal_notification() -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3607",
            days_left=19,
        )
    )
    async with await NotificationWorkflowStory.open(transcript.definitions()) as story:
        await story.run()

    assert [event[0] for event in transcript.events] == [
        "prepare",
        "deliver",
        "cleanup",
    ], "ordinary notification skipped delivery/cleanup or deleted its recurring Schedule"


async def test_deletes_the_schedule_after_delivering_death_day() -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3613",
            days_left=0,
        )
    )
    async with await NotificationWorkflowStory.open(transcript.definitions()) as story:
        await story.run()

    assert [event[0] for event in transcript.events] == [
        "prepare",
        "deliver",
        "cleanup",
        "delete_schedule",
    ], "death-day notification left its Temporal Schedule active"


async def test_reconciles_a_schedule_without_an_enabled_mortal() -> None:
    transcript = NotificationActivityTranscript(prepare_outcome=None)
    async with await NotificationWorkflowStory.open(transcript.definitions()) as story:
        await story.run()

    assert [event[0] for event in transcript.events] == [
        "prepare",
        "delete_schedule",
        "cleanup",
    ], "stale Schedule was not removed when notification preferences disappeared"


async def test_forbidden_delivery_deactivates_the_mortal() -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3617",
            days_left=7,
        ),
        delivery_outcome=ApplicationError(
            "recipient blocked the bot",
            type="TelegramRecipientUnavailable",
            non_retryable=True,
        ),
    )
    async with await NotificationWorkflowStory.open(transcript.definitions()) as story:
        await story.run()

    assert [event[0] for event in transcript.events] == [
        "prepare",
        "deliver",
        "deactivate",
        "cleanup",
    ], "Telegram Forbidden did not remove the Mortal and its Schedule"


async def test_best_effort_cleanup_survives_delivery_and_cleanup_failures() -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3623",
            days_left=3,
        ),
        delivery_outcome=ApplicationError("Telegram unavailable", non_retryable=True),
        cleanup_outcome=ApplicationError("Redis unavailable", non_retryable=True),
    )
    async with await NotificationWorkflowStory.open(transcript.definitions()) as story:
        await story.run()

    assert [event[0] for event in transcript.events] == [
        "prepare",
        "deliver",
        "cleanup",
    ], "transient notification failure incorrectly deactivated the Mortal"


@pytest.mark.parametrize(
    "failed_operation",
    [
        "deactivate",
        "delete_schedule",
    ],
)
async def test_lifecycle_activity_failure_does_not_hide_delivery_outcome(
    failed_operation: str,
) -> None:
    lifecycle_failure = ApplicationError(
        f"{failed_operation} unavailable",
        non_retryable=True,
    )
    forbidden = failed_operation == "deactivate"
    transcript = NotificationActivityTranscript(
        prepare_outcome=(
            PreparedMortalNotification(
                response_key="telegram:notification:3631",
                days_left=5,
            )
            if forbidden
            else None
        ),
        delivery_outcome=(
            ApplicationError(
                "recipient blocked the bot",
                type="TelegramRecipientUnavailable",
                non_retryable=True,
            )
            if forbidden
            else None
        ),
        deactivate_outcome=lifecycle_failure if forbidden else None,
        delete_schedule_outcome=lifecycle_failure if not forbidden else None,
    )
    async with await NotificationWorkflowStory.open(transcript.definitions()) as story:
        await story.run()

    assert failed_operation in [cast(str, event[0]) for event in transcript.events]


async def test_preparation_failure_fails_the_notification_workflow() -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=ApplicationError("PostgreSQL unavailable", non_retryable=True)
    )
    async with await NotificationWorkflowStory.open(transcript.definitions()) as story:
        with pytest.raises(WorkflowFailureError):
            await story.run()

    assert [event[0] for event in transcript.events] == ["prepare"], (
        "failed preparation continued into notification delivery or lifecycle cleanup"
    )
