from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_NOTIFICATION_RESPONSE_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    PreparedResponseDeliveryOutcome,
)
from sein_zum_tode.mortals.activities import (
    DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
    MortalActivityInput,
)
from sein_zum_tode.notifications.models import (
    MORTAL_NOTIFICATION_WORKFLOW_NAME,
    PLAN_MORTAL_NOTIFICATION_DELIVERY_ACTIVITY_NAME,
    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
    MortalNotificationDeliveryPlan,
    MortalNotificationWorkflowInput,
    PlanMortalNotificationDeliveryInput,
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
)
from sein_zum_tode.notifications.workflow import MortalNotificationWorkflow

pytestmark = [
    pytest.mark.deep,
    pytest.mark.asyncio(loop_scope="module"),
]


def result_or_raise(value: object) -> object:
    if isinstance(value, BaseException):
        raise value
    return value


class NotificationActivityTranscript:
    def __init__(
        self,
        *,
        prepare_outcome: object,
        plan_outcome: object = MortalNotificationDeliveryPlan.ending_at(
            datetime(2100, 1, 1, tzinfo=UTC),
        ),
        prepare_outcomes: tuple[object, ...] = (),
        delivery_outcome: object = PreparedResponseDeliveryOutcome.DELIVERED,
        delivery_outcomes: tuple[object, ...] = (),
        cleanup_outcome: object = None,
        mark_unreachable_outcome: object = None,
        delete_schedule_outcome: object = None,
    ) -> None:
        self.plan_outcome = plan_outcome
        self.prepare_outcomes = list(prepare_outcomes or (prepare_outcome,))
        self.delivery_outcomes = list(delivery_outcomes or (delivery_outcome,))
        self.cleanup_outcome = cleanup_outcome
        self.mark_unreachable_outcome = mark_unreachable_outcome
        self.delete_schedule_outcome = delete_schedule_outcome
        self.events: list[tuple[object, ...]] = []

    @activity.defn(name=PLAN_MORTAL_NOTIFICATION_DELIVERY_ACTIVITY_NAME)
    async def plan(
        self,
        input: PlanMortalNotificationDeliveryInput,
    ) -> MortalNotificationDeliveryPlan | None:
        self.events.append(("plan", input.mortal_id))
        return cast(
            MortalNotificationDeliveryPlan | None,
            result_or_raise(self.plan_outcome),
        )

    @activity.defn(name=PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME)
    async def prepare(
        self,
        input: PrepareMortalNotificationInput,
    ) -> PreparedMortalNotification | None:
        self.events.append(("prepare", input.mortal_id, input.response_key))
        return cast(
            PreparedMortalNotification | None,
            result_or_raise(self._next(self.prepare_outcomes)),
        )

    @activity.defn(name=DELIVER_NOTIFICATION_RESPONSE_ACTIVITY_NAME)
    async def deliver(
        self,
        input: DeliverResponseInput,
    ) -> PreparedResponseDeliveryOutcome:
        self.events.append(("deliver", input.user_id, input.response_key))
        return cast(
            PreparedResponseDeliveryOutcome,
            result_or_raise(self._next(self.delivery_outcomes)),
        )

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        self.events.append(("cleanup", input.user_id, input.keys))
        result_or_raise(self.cleanup_outcome)

    @activity.defn(name=MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME)
    async def mark_unreachable(self, input: MortalActivityInput) -> None:
        self.events.append(("mark_unreachable", input.mortal_id))
        result_or_raise(self.mark_unreachable_outcome)

    @activity.defn(name=DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME)
    async def delete_schedule(self, input: MortalActivityInput) -> None:
        self.events.append(("delete_schedule", input.mortal_id))
        result_or_raise(self.delete_schedule_outcome)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.plan,
            self.prepare,
            self.deliver,
            self.cleanup,
            self.mark_unreachable,
            self.delete_schedule,
        ]

    def _next(self, outcomes: list[object]) -> object:
        return outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]


class NotificationActivityRouter:
    def __init__(self) -> None:
        self._transcript: NotificationActivityTranscript | None = None

    def use(self, transcript: NotificationActivityTranscript) -> None:
        self._transcript = transcript

    def selected(self) -> NotificationActivityTranscript:
        if self._transcript is None:
            raise RuntimeError("Notification Activity transcript is not selected")
        return self._transcript

    @activity.defn(name=PLAN_MORTAL_NOTIFICATION_DELIVERY_ACTIVITY_NAME)
    async def plan(
        self,
        input: PlanMortalNotificationDeliveryInput,
    ) -> MortalNotificationDeliveryPlan | None:
        return await self.selected().plan(input)

    @activity.defn(name=PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME)
    async def prepare(
        self,
        input: PrepareMortalNotificationInput,
    ) -> PreparedMortalNotification | None:
        return await self.selected().prepare(input)

    @activity.defn(name=DELIVER_NOTIFICATION_RESPONSE_ACTIVITY_NAME)
    async def deliver(
        self,
        input: DeliverResponseInput,
    ) -> PreparedResponseDeliveryOutcome:
        return await self.selected().deliver(input)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        await self.selected().cleanup(input)

    @activity.defn(name=MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME)
    async def mark_unreachable(self, input: MortalActivityInput) -> None:
        await self.selected().mark_unreachable(input)

    @activity.defn(name=DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME)
    async def delete_schedule(self, input: MortalActivityInput) -> None:
        await self.selected().delete_schedule(input)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.plan,
            self.prepare,
            self.deliver,
            self.cleanup,
            self.mark_unreachable,
            self.delete_schedule,
        ]


class NotificationWorkflowStory:
    def __init__(
        self,
        *,
        environment: WorkflowEnvironment,
        worker: Worker,
        task_queue: str,
        activities: NotificationActivityRouter,
    ) -> None:
        self.environment = environment
        self.worker = worker
        self.task_queue = task_queue
        self.activities = activities

    @classmethod
    async def open(
        cls,
        *,
        environment: WorkflowEnvironment,
    ) -> NotificationWorkflowStory:
        task_queue = f"deep-notification-{uuid4()}"
        activities = NotificationActivityRouter()
        worker = Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[MortalNotificationWorkflow],
            activities=activities.definitions(),
        )
        await worker.__aenter__()
        return cls(
            environment=environment,
            worker=worker,
            task_queue=task_queue,
            activities=activities,
        )

    async def close(self) -> None:
        await self.worker.__aexit__(None, None, None)

    async def run(
        self,
        transcript: NotificationActivityTranscript,
        *,
        delivery_deadline: datetime | None = None,
    ) -> None:
        self.activities.use(transcript)
        with self.environment.auto_time_skipping_disabled():
            await self.environment.client.execute_workflow(
                MORTAL_NOTIFICATION_WORKFLOW_NAME,
                MortalNotificationWorkflowInput(
                    mortal_id=360_007,
                    activity_retry_timeout_seconds=7,
                    delivery_deadline=(
                        delivery_deadline.isoformat() if delivery_deadline is not None else None
                    ),
                ),
                id=f"deep-notification-{uuid4()}",
                task_queue=self.task_queue,
            )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def notification_story(
    temporal_environment: WorkflowEnvironment,
) -> AsyncIterator[NotificationWorkflowStory]:
    story = await NotificationWorkflowStory.open(environment=temporal_environment)
    yield story
    await story.close()


async def test_delivers_and_cleans_a_nonterminal_notification(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3607",
            days_left=19,
        )
    )
    await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == [
        "plan",
        "prepare",
        "deliver",
        "cleanup",
    ], "ordinary notification skipped delivery/cleanup or deleted its recurring Schedule"


async def test_finishes_without_preparation_when_no_future_action_exists(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=None,
        plan_outcome=None,
    )

    await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == ["plan"], (
        "workflow prepared a notification without a future Schedule action"
    )


async def test_finishes_when_the_explicit_delivery_deadline_has_passed(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(prepare_outcome=None)

    await notification_story.run(
        transcript,
        delivery_deadline=datetime(2000, 1, 1, tzinfo=UTC),
    )

    assert transcript.events == [], "expired delivery window still called notification Activities"


async def test_planning_failure_fails_the_notification_workflow(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=None,
        plan_outcome=ApplicationError("Schedule unavailable", non_retryable=True),
    )

    with pytest.raises(WorkflowFailureError):
        await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == ["plan"], (
        "failed delivery planning continued into notification preparation"
    )


async def test_deletes_the_schedule_after_delivering_death_day(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3613",
            days_left=0,
        )
    )
    await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == [
        "plan",
        "prepare",
        "deliver",
        "cleanup",
        "delete_schedule",
    ], "death-day notification left its Temporal Schedule active"


async def test_reconciles_a_schedule_without_an_enabled_mortal(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(prepare_outcome=None)
    await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == [
        "plan",
        "prepare",
        "delete_schedule",
        "cleanup",
    ], "stale Schedule was not removed when notification preferences disappeared"


async def test_forbidden_delivery_marks_the_mortal_unreachable(
    notification_story: NotificationWorkflowStory,
) -> None:
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
    await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == [
        "plan",
        "prepare",
        "deliver",
        "mark_unreachable",
        "cleanup",
    ], "Telegram Forbidden did not mark the Mortal unreachable and remove its Schedule"


async def test_best_effort_cleanup_survives_delivery_and_cleanup_failures(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3623",
            days_left=3,
        ),
        delivery_outcome=ApplicationError("Telegram unavailable", non_retryable=True),
        cleanup_outcome=ApplicationError("Redis unavailable", non_retryable=True),
    )
    await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == [
        "plan",
        "prepare",
        "deliver",
        "cleanup",
    ], "transient notification failure incorrectly marked the Mortal unreachable"


async def test_reprepares_an_expired_notification_before_delivery_deadline(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=PreparedMortalNotification(
            response_key="telegram:notification:3627:old",
            days_left=4,
        ),
        prepare_outcomes=(
            PreparedMortalNotification(
                response_key="telegram:notification:3627:old",
                days_left=4,
            ),
            PreparedMortalNotification(
                response_key="telegram:notification:3627:fresh",
                days_left=3,
            ),
        ),
        delivery_outcomes=(
            PreparedResponseDeliveryOutcome.RESPONSE_EXPIRED,
            PreparedResponseDeliveryOutcome.DELIVERED,
        ),
    )

    await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == [
        "plan",
        "prepare",
        "deliver",
        "prepare",
        "deliver",
        "cleanup",
    ], "expired notification was not recomputed and delivered within the same schedule window"


@pytest.mark.parametrize(
    "failed_operation",
    [
        "mark_unreachable",
        "delete_schedule",
    ],
)
async def test_lifecycle_activity_failure_does_not_hide_delivery_outcome(
    failed_operation: str,
    notification_story: NotificationWorkflowStory,
) -> None:
    lifecycle_failure = ApplicationError(
        f"{failed_operation} unavailable",
        non_retryable=True,
    )
    forbidden = failed_operation == "mark_unreachable"
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
        mark_unreachable_outcome=lifecycle_failure if forbidden else None,
        delete_schedule_outcome=lifecycle_failure if not forbidden else None,
    )
    await notification_story.run(transcript)

    assert failed_operation in [cast(str, event[0]) for event in transcript.events]


async def test_preparation_failure_fails_the_notification_workflow(
    notification_story: NotificationWorkflowStory,
) -> None:
    transcript = NotificationActivityTranscript(
        prepare_outcome=ApplicationError("PostgreSQL unavailable", non_retryable=True)
    )
    with pytest.raises(WorkflowFailureError):
        await notification_story.run(transcript)

    assert [event[0] for event in transcript.events] == ["plan", "prepare"], (
        "failed preparation continued into notification delivery or lifecycle cleanup"
    )
