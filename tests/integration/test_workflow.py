import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from types import TracebackType
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from sein_zum_tode.bot.activities import (
    CleanupTelegramPayloadsActivity,
    DeliverTelegramResponseActivity,
    InspectTelegramUpdateActivity,
    PrepareTelegramResponseActivities,
)
from sein_zum_tode.bot.conversation.models import (
    CONVERSATION_FINISHED_SIGNAL_NAME,
    TELEGRAM_CONVERSATION_WORKFLOW_NAME,
    ConversationFinishedSignal,
    ConversationWorkflowInput,
)
from sein_zum_tode.bot.conversation.workflow import TelegramConversationWorkflow
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_ECHO_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    PREPARE_UNSUPPORTED_ACTIVITY_NAME,
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TELEGRAM_USER_WORKFLOW_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    InspectUpdateInput,
    PrepareResponseInput,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.mortals.activities import (
    CHECK_MORTAL_QUOTA_ACTIVITY_NAME,
    DEACTIVATE_MORTAL_ACTIVITY_NAME,
    ENSURE_MORTAL_ACTIVITY_NAME,
    RESET_MORTAL_ACTIVITY_NAME,
    MortalActivityInput,
)
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.models import CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME
from tests.support import (
    TEST_TIMEOUT_SECONDS,
    BotContents,
    MortalMemory,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
)

pytestmark = [
    pytest.mark.deep,
    pytest.mark.asyncio(loop_scope="module"),
]


@workflow.defn(name=TELEGRAM_CONVERSATION_WORKFLOW_NAME)
class FailingTelegramConversationWorkflow:
    @workflow.run
    async def run(self, input: ConversationWorkflowInput) -> None:
        raise ApplicationError("conversation workflow failed", non_retryable=True)


@workflow.defn(name=TELEGRAM_CONVERSATION_WORKFLOW_NAME)
class DelayedFailingTelegramConversationWorkflow:
    def __init__(self) -> None:
        self._released = False

    @workflow.signal
    async def release_failure(self) -> None:
        self._released = True

    @workflow.run
    async def run(self, input: ConversationWorkflowInput) -> None:
        await workflow.wait_condition(lambda: self._released)
        raise ApplicationError("conversation workflow failed", non_retryable=True)


@workflow.defn(name=TELEGRAM_CONVERSATION_WORKFLOW_NAME)
class DelayedFinishedTelegramConversationWorkflow:
    def __init__(self) -> None:
        self._finished_signal_sent = False
        self._released = False

    @workflow.signal
    async def release_completion(self) -> None:
        self._released = True

    @workflow.query
    def finished_signal_sent(self) -> bool:
        return self._finished_signal_sent

    @workflow.run
    async def run(self, input: ConversationWorkflowInput) -> None:
        parent = workflow.get_external_workflow_handle(input.owner_workflow_id)
        await parent.signal(
            CONVERSATION_FINISHED_SIGNAL_NAME,
            ConversationFinishedSignal(conversation_key=input.conversation_key),
        )
        self._finished_signal_sent = True
        await workflow.wait_condition(lambda: self._released)


class ActivityTranscript:
    def __init__(
        self,
        inspections: dict[str, InspectionKind],
        failing_inspection: str | None,
        failing_cleanup: bool,
        failing_response: str | None = None,
        blocked_inspection: str | None = None,
        failing_registration: bool = False,
        failing_deactivation: bool = False,
        forbidden_delivery: str | None = None,
        failing_reset: bool = False,
        quota_outcomes: list[object] | None = None,
    ) -> None:
        self.inspections = inspections
        self.failing_inspection = failing_inspection
        self.failing_cleanup = failing_cleanup
        self.failing_response = failing_response
        self.blocked_inspection = blocked_inspection
        self.failing_registration = failing_registration
        self.failing_deactivation = failing_deactivation
        self.forbidden_delivery = forbidden_delivery
        self.failing_reset = failing_reset
        self.quota_outcomes = list(quota_outcomes or [])
        self.events: list[tuple[str, str, int | None]] = []
        self.changed = asyncio.Event()
        self.inspection_started = asyncio.Event()
        self.release_inspection = asyncio.Event()

    def record(self, operation: str, update_key: str, user_id: int | None) -> None:
        self.events.append((operation, update_key, user_id))
        self.changed.set()

    @activity.defn(name=INSPECT_UPDATE_ACTIVITY_NAME)
    async def inspect(self, input: InspectUpdateInput) -> InspectedUpdate:
        self.record(
            operation="inspect",
            update_key=input.update_key,
            user_id=input.user_id,
        )
        if input.update_key == self.blocked_inspection:
            self.inspection_started.set()
            await self.release_inspection.wait()
        if input.update_key == self.failing_inspection:
            raise ApplicationError("inspection rejected", non_retryable=True)
        return InspectedUpdate(
            kind=self.inspections[input.update_key],
            update_key=input.update_key,
            chat_id=input.user_id + 17,
        )

    @activity.defn(name=PREPARE_ECHO_ACTIVITY_NAME)
    async def prepare_echo(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_echo",
            update_key=input.update_key,
            user_id=input.user_id,
        )
        if input.update_key == self.failing_response:
            raise ApplicationError("response rejected", non_retryable=True)

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_help",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=PREPARE_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_unsupported(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_unsupported",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_group_unsupported",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME)
    async def prepare_limit_exhausted(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_limit",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME)
    async def configure_notifications(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="configure_notifications",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        self.record(
            operation="deliver",
            update_key=input.update_key or "missing-update-key",
            user_id=input.user_id,
        )
        if input.update_key == self.forbidden_delivery:
            raise ApplicationError(
                "recipient blocked the bot",
                type="TelegramRecipientUnavailable",
                non_retryable=True,
            )

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        self.record(
            operation="cleanup",
            update_key=input.update_key or "missing-update-key",
            user_id=input.user_id,
        )
        if self.failing_cleanup:
            raise ApplicationError("cleanup rejected", non_retryable=True)

    @activity.defn(name=ENSURE_MORTAL_ACTIVITY_NAME)
    async def ensure_mortal(self, input: MortalActivityInput) -> None:
        if self.failing_registration:
            raise ApplicationError("PostgreSQL unavailable", non_retryable=True)

    @activity.defn(name=DEACTIVATE_MORTAL_ACTIVITY_NAME)
    async def deactivate_mortal(self, input: MortalActivityInput) -> None:
        self.record(
            operation="deactivate",
            update_key="mortal-lifecycle",
            user_id=input.mortal_id,
        )
        if self.failing_deactivation:
            raise ApplicationError("deactivation unavailable", non_retryable=True)

    @activity.defn(name=RESET_MORTAL_ACTIVITY_NAME)
    async def reset_mortal(self, input: MortalActivityInput) -> None:
        if self.failing_reset:
            raise ApplicationError("reset unavailable", non_retryable=True)

    @activity.defn(name=CHECK_MORTAL_QUOTA_ACTIVITY_NAME)
    async def has_quota(self, input: MortalActivityInput) -> bool:
        outcome = self.quota_outcomes.pop(0) if self.quota_outcomes else True
        if isinstance(outcome, BaseException):
            raise outcome
        return bool(outcome)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.inspect,
            self.prepare_echo,
            self.prepare_help,
            self.prepare_unsupported,
            self.prepare_group_unsupported,
            self.prepare_limit_exhausted,
            self.configure_notifications,
            self.deliver,
            self.cleanup,
            self.ensure_mortal,
            self.deactivate_mortal,
            self.reset_mortal,
            self.has_quota,
        ]

    async def wait_for(self, operation: str, count: int) -> None:
        while sum(event[0] == operation for event in self.events) < count:
            self.changed.clear()
            await asyncio.wait_for(
                self.changed.wait(),
                timeout=TEST_TIMEOUT_SECONDS,
            )


class ActivityRouter:
    def __init__(self) -> None:
        self._activities: dict[str, Callable[[object], Awaitable[object]]] = {}

    def use(self, activities: Sequence[Callable[..., object]]) -> None:
        self._activities = {
            activity_definition.__name__: cast(
                Callable[[object], Awaitable[object]],
                activity_definition,
            )
            for activity_definition in activities
        }

    def selected(self, name: str) -> Callable[[object], Awaitable[object]]:
        try:
            return self._activities[name]
        except KeyError as error:
            raise RuntimeError(f"Activity {name} is not selected") from error

    @activity.defn(name=INSPECT_UPDATE_ACTIVITY_NAME)
    async def inspect(self, input: InspectUpdateInput) -> InspectedUpdate:
        return cast(InspectedUpdate, await self.selected("inspect")(input))

    @activity.defn(name=PREPARE_ECHO_ACTIVITY_NAME)
    async def prepare_echo(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_echo")(input)

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_help")(input)

    @activity.defn(name=PREPARE_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_unsupported(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_unsupported")(input)

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_group_unsupported")(input)

    @activity.defn(name=PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME)
    async def prepare_limit_exhausted(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_limit_exhausted")(input)

    @activity.defn(name=CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME)
    async def configure_notifications(self, input: PrepareResponseInput) -> None:
        await self.selected("configure_notifications")(input)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        await self.selected("deliver")(input)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        await self.selected("cleanup")(input)

    @activity.defn(name=ENSURE_MORTAL_ACTIVITY_NAME)
    async def ensure_mortal(self, input: MortalActivityInput) -> None:
        await self.selected("ensure_mortal")(input)

    @activity.defn(name=DEACTIVATE_MORTAL_ACTIVITY_NAME)
    async def deactivate_mortal(self, input: MortalActivityInput) -> None:
        await self.selected("deactivate_mortal")(input)

    @activity.defn(name=RESET_MORTAL_ACTIVITY_NAME)
    async def reset_mortal(self, input: MortalActivityInput) -> None:
        await self.selected("reset_mortal")(input)

    @activity.defn(name=CHECK_MORTAL_QUOTA_ACTIVITY_NAME)
    async def has_quota(self, input: MortalActivityInput) -> bool:
        return cast(bool, await self.selected("has_quota")(input))

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.inspect,
            self.prepare_echo,
            self.prepare_help,
            self.prepare_unsupported,
            self.prepare_group_unsupported,
            self.prepare_limit_exhausted,
            self.configure_notifications,
            self.deliver,
            self.cleanup,
            self.ensure_mortal,
            self.deactivate_mortal,
            self.reset_mortal,
            self.has_quota,
        ]


class WorkflowWorkerPool:
    def __init__(
        self,
        *,
        environment: WorkflowEnvironment,
        activities: ActivityRouter,
        workers: dict[type, Worker],
        task_queues: dict[type, str],
    ) -> None:
        self.environment = environment
        self.activities = activities
        self.workers = workers
        self.task_queues = task_queues

    @classmethod
    async def open(
        cls,
        *,
        environment: WorkflowEnvironment,
    ) -> WorkflowWorkerPool:
        activities = ActivityRouter()
        workers: dict[type, Worker] = {}
        task_queues: dict[type, str] = {}
        conversation_workflows = (
            TelegramConversationWorkflow,
            FailingTelegramConversationWorkflow,
            DelayedFailingTelegramConversationWorkflow,
            DelayedFinishedTelegramConversationWorkflow,
        )
        for conversation_workflow in conversation_workflows:
            task_queue = f"deep-telegram-{uuid4()}"
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[TelegramUserWorkflow, conversation_workflow],
                activities=activities.definitions(),
            )
            await worker.__aenter__()
            workers[conversation_workflow] = worker
            task_queues[conversation_workflow] = task_queue
        return cls(
            environment=environment,
            activities=activities,
            workers=workers,
            task_queues=task_queues,
        )

    async def close(self) -> None:
        await asyncio.gather(
            *(worker.__aexit__(None, None, None) for worker in self.workers.values())
        )

    def select(
        self,
        *,
        activities: Sequence[Callable[..., object]],
        conversation_workflow: type,
    ) -> str:
        self.activities.use(activities)
        return self.task_queues[conversation_workflow]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def workflow_worker_pool(
    temporal_environment: WorkflowEnvironment,
) -> AsyncIterator[WorkflowWorkerPool]:
    pool = await WorkflowWorkerPool.open(environment=temporal_environment)
    yield pool
    await pool.close()


class WorkflowStory:
    def __init__(
        self,
        *,
        environment: WorkflowEnvironment,
        task_queue: str,
    ) -> None:
        self.environment = environment
        self.task_queue = task_queue
        self.handles: list[WorkflowHandle[TelegramUserWorkflow, None]] = []

    @classmethod
    async def open(
        cls,
        *,
        pool: WorkflowWorkerPool,
        activities: Sequence[Callable[..., object]],
        conversation_workflow: type = TelegramConversationWorkflow,
    ) -> WorkflowStory:
        task_queue = pool.select(
            activities=activities,
            conversation_workflow=conversation_workflow,
        )
        return cls(
            environment=pool.environment,
            task_queue=task_queue,
        )

    async def __aenter__(self) -> WorkflowStory:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        for handle in self.handles:
            try:
                await handle.terminate("Integration test completed")
            except RPCError as error:
                if error.status is not RPCStatusCode.NOT_FOUND:
                    raise

    async def start(
        self,
        update_key: str,
        *,
        continue_after: int | None,
    ) -> WorkflowHandle[TelegramUserWorkflow, None]:
        handle = await self.environment.client.start_workflow(
            TELEGRAM_USER_WORKFLOW_NAME,
            UserWorkflowInput(
                user_id=173_357,
                activity_retry_timeout_seconds=7,
                continue_as_new_after_updates=continue_after,
            ),
            id=f"deep-user-{uuid4()}",
            task_queue=self.task_queue,
            start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
            start_signal_args=[TelegramUpdateSignal(redis_key=update_key)],
        )
        self.handles.append(handle)
        return handle

    async def wait_for_new_run(
        self,
        handle: WorkflowHandle[TelegramUserWorkflow, None],
        previous_run: str,
    ) -> str:
        async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
            while True:
                current = (
                    await handle.describe()
                ).raw_description.workflow_execution_info.execution.run_id
                if current != previous_run:
                    return current


async def test_routes_unique_signals_through_the_complete_pipeline(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    kinds = {
        "redis:echo:1733": InspectionKind.ECHO,
        "redis:help:1741": InspectionKind.HELP,
        "redis:unsupported:1747": InspectionKind.UNSUPPORTED,
        "redis:group:1753": InspectionKind.GROUP_UNSUPPORTED,
    }
    transcript = ActivityTranscript(
        inspections=kinds,
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start("redis:echo:1733", continue_after=None)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key="redis:echo:1733"),
        )
        for key in ("redis:help:1741", "redis:unsupported:1747", "redis:group:1753"):
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=key),
            )
        await transcript.wait_for("cleanup", 4)

        assert transcript.events == [
            ("inspect", "redis:echo:1733", 173_357),
            ("prepare_echo", "redis:echo:1733", 173_357),
            ("deliver", "redis:echo:1733", 173_357),
            ("cleanup", "redis:echo:1733", 173_357),
            ("inspect", "redis:help:1741", 173_357),
            ("prepare_help", "redis:help:1741", 173_357),
            ("deliver", "redis:help:1741", 173_357),
            ("cleanup", "redis:help:1741", 173_357),
            ("inspect", "redis:unsupported:1747", 173_357),
            ("prepare_unsupported", "redis:unsupported:1747", 173_357),
            ("deliver", "redis:unsupported:1747", 173_357),
            ("cleanup", "redis:unsupported:1747", 173_357),
            ("inspect", "redis:group:1753", 173_357),
            ("prepare_group_unsupported", "redis:group:1753", 173_357),
            ("deliver", "redis:group:1753", 173_357),
            ("cleanup", "redis:group:1753", 173_357),
        ], "workflow duplicated a signal or selected an incorrect Activity pipeline"


async def test_routes_notification_callback_without_entering_a_conversation(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:notification-callback:1757"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.NOTIFICATION_SELECTION},
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        await story.start(update_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)

    assert transcript.events == [
        ("inspect", update_key, 173_357),
        ("configure_notifications", update_key, 173_357),
        ("deliver", update_key, 173_357),
        ("cleanup", update_key, 173_357),
    ], "notification callback was signalled to a questionnaire or skipped delivery"


@pytest.mark.parametrize(
    ("quota_outcome", "expected_operations"),
    [
        (
            False,
            ["inspect", "prepare_limit", "deliver", "cleanup"],
        ),
        (
            ApplicationError("quota unavailable", non_retryable=True),
            ["inspect", "cleanup"],
        ),
    ],
)
async def test_handles_exhausted_or_unavailable_quota_before_begin(
    quota_outcome: object,
    expected_operations: list[str],
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:begin-quota:1758"
    stop_key = "redis:stop-after-begin-quota:1759"
    transcript = ActivityTranscript(
        inspections={
            update_key: InspectionKind.BEGIN,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
        quota_outcomes=[quota_outcome],
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        conversation_workflow=DelayedFailingTelegramConversationWorkflow,
    ) as story:
        handle = await story.start(update_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        operations = [event[0] for event in transcript.events]
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert operations == expected_operations


@pytest.mark.parametrize(
    ("second_quota", "expected_operations"),
    [
        (
            False,
            ["inspect", "cleanup", "inspect", "prepare_limit", "deliver", "cleanup"],
        ),
        (
            ApplicationError("quota unavailable", non_retryable=True),
            ["inspect", "cleanup", "inspect", "cleanup"],
        ),
    ],
)
async def test_does_not_restart_an_active_conversation_without_available_quota(
    second_quota: object,
    expected_operations: list[str],
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    first_key = "redis:begin-active-quota:first"
    second_key = "redis:begin-active-quota:second"
    transcript = ActivityTranscript(
        inspections={
            first_key: InspectionKind.BEGIN,
            second_key: InspectionKind.BEGIN,
        },
        failing_inspection=None,
        failing_cleanup=False,
        quota_outcomes=[True, second_quota],
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        conversation_workflow=DelayedFailingTelegramConversationWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(first_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=second_key),
            )
            await transcript.wait_for("cleanup", 2)

    assert [event[0] for event in transcript.events] == expected_operations


async def test_keeps_processing_after_activity_and_cleanup_failures(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:fractured:1759": InspectionKind.ECHO,
            "redis:survivor:1777": InspectionKind.HELP,
        },
        failing_inspection="redis:fractured:1759",
        failing_cleanup=True,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start("redis:fractured:1759", continue_after=None)
        await transcript.wait_for("cleanup", 1)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key="redis:survivor:1777"),
        )
        await transcript.wait_for("cleanup", 2)

        assert transcript.events[:4] == [
            ("inspect", "redis:fractured:1759", 173_357),
            ("cleanup", "redis:fractured:1759", 173_357),
            ("inspect", "redis:survivor:1777", 173_357),
            ("prepare_help", "redis:survivor:1777", 173_357),
        ], "one failed update or cleanup terminated the per-user workflow"


async def test_keeps_processing_after_response_preparation_failure(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:response-failure:1779": InspectionKind.ECHO,
            "redis:response-survivor:1781": InspectionKind.HELP,
        },
        failing_inspection=None,
        failing_cleanup=False,
        failing_response="redis:response-failure:1779",
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start("redis:response-failure:1779", continue_after=None)
        await transcript.wait_for("cleanup", 1)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key="redis:response-survivor:1781"),
        )
        await transcript.wait_for("cleanup", 2)

        assert transcript.events[:5] == [
            ("inspect", "redis:response-failure:1779", 173_357),
            ("prepare_echo", "redis:response-failure:1779", 173_357),
            ("cleanup", "redis:response-failure:1779", 173_357),
            ("inspect", "redis:response-survivor:1781", 173_357),
            ("prepare_help", "redis:response-survivor:1781", 173_357),
        ], "failed response preparation terminated the per-user workflow"


async def test_recovers_when_a_child_conversation_workflow_fails(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-failed-child:1783"
    echo_key = "redis:echo-after-failed-child:1787"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            echo_key: InspectionKind.ECHO,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        conversation_workflow=FailingTelegramConversationWorkflow,
    ) as story:
        handle = await story.start(begin_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        child_id = f"{handle.id}:conversation:{begin_key}"
        child = story.environment.client.get_workflow_handle(child_id)
        with pytest.raises(WorkflowFailureError):
            await child.result()
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=echo_key),
        )
        await transcript.wait_for("cleanup", 2)

        assert transcript.events[-4:] == [
            ("inspect", echo_key, 173_357),
            ("prepare_echo", echo_key, 173_357),
            ("deliver", echo_key, 173_357),
            ("cleanup", echo_key, 173_357),
        ], "failed child conversation prevented later updates from using normal routing"


async def test_reroutes_an_update_when_child_fails_during_inspection(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-delayed-failure:1789"
    echo_key = "redis:echo-during-child-failure:1801"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            echo_key: InspectionKind.ECHO,
        },
        failing_inspection=None,
        failing_cleanup=False,
        blocked_inspection=echo_key,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        conversation_workflow=DelayedFailingTelegramConversationWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(begin_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=echo_key),
            )
            await asyncio.wait_for(
                transcript.inspection_started.wait(),
                timeout=TEST_TIMEOUT_SECONDS,
            )
            child_id = f"{handle.id}:conversation:{begin_key}"
            child = story.environment.client.get_workflow_handle(child_id)
            await child.signal(DelayedFailingTelegramConversationWorkflow.release_failure)
            with pytest.raises(WorkflowFailureError):
                await child.result()
            transcript.release_inspection.set()
            await transcript.wait_for("cleanup", 2)

        assert transcript.events[-4:] == [
            ("inspect", echo_key, 173_357),
            ("prepare_echo", echo_key, 173_357),
            ("deliver", echo_key, 173_357),
            ("cleanup", echo_key, 173_357),
        ], "update inspected during child failure was not rerouted to normal echo processing"


async def test_carries_deduplication_state_through_continue_as_new(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:first:1783": InspectionKind.ECHO,
            "redis:second:1787": InspectionKind.HELP,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start("redis:first:1783", continue_after=1)
        first_run = (
            await handle.describe()
        ).raw_description.workflow_execution_info.execution.run_id
        await transcript.wait_for("cleanup", 1)
        current_run = await story.wait_for_new_run(handle, first_run)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key="redis:first:1783"),
        )
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key="redis:second:1787"),
        )
        await transcript.wait_for("cleanup", 2)

        assert (
            current_run != first_run,
            [event for event in transcript.events if event[0] == "inspect"],
        ) == (
            True,
            [
                ("inspect", "redis:first:1783", 173_357),
                ("inspect", "redis:second:1787", 173_357),
            ],
        ), "Continue-As-New lost recent keys or failed to rotate Workflow History"


async def test_keeps_sensitive_message_text_out_of_workflow_history(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    secret = "The five boxing wizards jump quickly over history 1789"
    update = TelegramUpdates.message(
        update_id=1789,
        user_id=173_357,
        chat_id=179_297,
        text=secret,
        chat_type="private",
    )
    telegram = TelegramMemory(
        update_result=update,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    inspect = InspectTelegramUpdateActivity(
        update_reader=telegram,
        logger=SilentLogger(),
    )
    prepare = PrepareTelegramResponseActivities(
        update_reader=telegram,
        response_store=telegram,
        ttl_seconds=1801,
        content=BotContents.debug(),
        mortals=MortalMemory({173_357: Mortal(id=173_357)}),
        logger=SilentLogger(),
    )
    deliver = DeliverTelegramResponseActivity(
        response_reader=telegram,
        sender=telegram,
        logger=SilentLogger(),
    )
    cleanup = CleanupTelegramPayloadsActivity(
        cleaner=telegram,
        logger=SilentLogger(),
    )
    definitions: Sequence[Callable[..., object]] = [
        inspect.inspect,
        prepare.prepare_echo,
        prepare.prepare_help,
        prepare.prepare_unsupported,
        prepare.prepare_group_unsupported,
        deliver.deliver,
        cleanup.cleanup,
        ActivityTranscript(
            inspections={},
            failing_inspection=None,
            failing_cleanup=False,
        ).ensure_mortal,
    ]
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=definitions,
    ) as story:
        handle = await story.start("telegram:updates:1801:1789", continue_after=None)
        await asyncio.wait_for(
            telegram.sent.wait(),
            timeout=TEST_TIMEOUT_SECONDS,
        )
        history = await handle.fetch_history()

        assert (
            ("send_text", 179_297, secret) in telegram.events,
            secret not in json.dumps(history.to_json_dict()),
        ) == (True, True), "Temporal persisted sensitive text or delivery changed it"


async def test_skips_processing_when_mortal_registration_fails(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:registration-failure:1811"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.ECHO},
        failing_inspection=None,
        failing_cleanup=False,
        failing_registration=True,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        await story.start(update_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)

    assert [event[0] for event in transcript.events] == [
        "inspect",
        "cleanup",
    ], "response pipeline ran without a successfully registered Mortal"


async def test_unblock_registers_silently_before_later_echo(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    unblock_key = "redis:unblocked:1823"
    echo_key = "redis:echo-after-unblock:1831"
    transcript = ActivityTranscript(
        inspections={
            unblock_key: InspectionKind.MORTAL_UNBLOCKED,
            echo_key: InspectionKind.ECHO,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(unblock_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=echo_key),
        )
        await transcript.wait_for("cleanup", 2)

    assert transcript.events == [
        ("inspect", unblock_key, 173_357),
        ("cleanup", unblock_key, 173_357),
        ("inspect", echo_key, 173_357),
        ("prepare_echo", echo_key, 173_357),
        ("deliver", echo_key, 173_357),
        ("cleanup", echo_key, 173_357),
    ], "unblock produced a Telegram response or failed to restore normal routing"


async def test_unblock_stays_silent_when_reset_fails(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    unblock_key = "redis:unblock-reset-failure:1837"
    transcript = ActivityTranscript(
        inspections={unblock_key: InspectionKind.MORTAL_UNBLOCKED},
        failing_inspection=None,
        failing_cleanup=False,
        failing_reset=True,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        await story.start(unblock_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)

    assert transcript.events == [
        ("inspect", unblock_key, 173_357),
        ("cleanup", unblock_key, 173_357),
    ], "failed unblock reset leaked a response or entered ordinary processing"


@pytest.mark.parametrize("failing_deactivation", [False, True])
async def test_block_deactivates_the_mortal_and_completes_parent(
    failing_deactivation: bool,
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:blocked:1847"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.MORTAL_BLOCKED},
        failing_inspection=None,
        failing_cleanup=False,
        failing_deactivation=failing_deactivation,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(update_key, continue_after=None)
        await handle.result()

    assert transcript.events == [
        ("inspect", update_key, 173_357),
        ("cleanup", update_key, 173_357),
        ("deactivate", "mortal-lifecycle", 173_357),
    ], "block update did not clean Redis, deactivate the Mortal, and stop its parent"


async def test_forbidden_delivery_deactivates_and_completes_parent(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:forbidden:1861"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.ECHO},
        failing_inspection=None,
        failing_cleanup=False,
        forbidden_delivery=update_key,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(update_key, continue_after=None)
        await handle.result()

    assert [event[0] for event in transcript.events] == [
        "inspect",
        "prepare_echo",
        "deliver",
        "deactivate",
        "cleanup",
    ], "Telegram Forbidden did not run fallback Mortal deletion before parent completion"


async def test_block_cancels_an_active_conversation_before_deactivation(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-before-block:1867"
    blocked_key = "redis:block-during-conversation:1871"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            blocked_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        conversation_workflow=DelayedFailingTelegramConversationWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(begin_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=blocked_key),
            )
            await handle.result()

    assert [event[0] for event in transcript.events[-3:]] == [
        "inspect",
        "cleanup",
        "deactivate",
    ], "block left an active questionnaire child or skipped Mortal deactivation"


async def test_waits_for_a_finished_child_before_routing_the_next_update(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-finishing-child:1873"
    echo_key = "redis:echo-after-finished-signal:1877"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            echo_key: InspectionKind.ECHO,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        conversation_workflow=DelayedFinishedTelegramConversationWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(begin_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            child_id = f"{handle.id}:conversation:{begin_key}"
            child = story.environment.client.get_workflow_handle(child_id)
            async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
                while not await child.query(
                    DelayedFinishedTelegramConversationWorkflow.finished_signal_sent
                ):
                    pass
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=echo_key),
            )
            await child.signal(DelayedFinishedTelegramConversationWorkflow.release_completion)
            await transcript.wait_for("cleanup", 2)

    assert transcript.events[-4:] == [
        ("inspect", echo_key, 173_357),
        ("prepare_echo", echo_key, 173_357),
        ("deliver", echo_key, 173_357),
        ("cleanup", echo_key, 173_357),
    ], "parent routed an update into a child that had stopped accepting signals"
