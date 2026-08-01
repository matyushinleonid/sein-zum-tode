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
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    PREPARE_LOCALIZATION_ACTIVITY_NAME,
    PREPARE_SCREAM_DENIED_ACTIVITY_NAME,
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
from sein_zum_tode.broadcasts.models import (
    TELEGRAM_SCREAM_WORKFLOW_NAME,
    ScreamRequest,
    ScreamWorkflowInput,
)
from sein_zum_tode.localization.models import (
    CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME,
)
from sein_zum_tode.mortals.activities import (
    CHECK_MORTAL_QUOTA_ACTIVITY_NAME,
    ENSURE_MORTAL_ACTIVITY_NAME,
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
    MortalActivityInput,
    MortalRegistration,
)
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.custom_schedule.models import (
    APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
    GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
    PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME,
    ApplyCustomNotificationScheduleInput,
    GenerateCustomNotificationScheduleInput,
    PrepareCustomNotificationFailureInput,
)
from sein_zum_tode.notifications.models import CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME
from sein_zum_tode.questionnaire.models import (
    QUESTIONNAIRE_FINISHED_SIGNAL_NAME,
    QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
    TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME,
    QuestionnaireFinishedSignal,
    QuestionnaireUpdateSignal,
    QuestionnaireWorkflowInput,
)
from sein_zum_tode.questionnaire.workflow import TelegramQuestionnaireWorkflow
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


@workflow.defn(name=TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME, sandboxed=False)
class FailingTelegramQuestionnaireWorkflow:
    @workflow.run
    async def run(self, input: QuestionnaireWorkflowInput) -> None:
        raise ApplicationError("questionnaire workflow failed", non_retryable=True)


@workflow.defn(name=TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME, sandboxed=False)
class DelayedFailingTelegramQuestionnaireWorkflow:
    def __init__(self) -> None:
        self._released = False

    @workflow.signal
    async def release_failure(self) -> None:
        self._released = True

    @workflow.run
    async def run(self, input: QuestionnaireWorkflowInput) -> None:
        await workflow.wait_condition(lambda: self._released)
        raise ApplicationError("questionnaire workflow failed", non_retryable=True)


@workflow.defn(name=TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME, sandboxed=False)
class DelayedFinishedTelegramQuestionnaireWorkflow:
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
    async def run(self, input: QuestionnaireWorkflowInput) -> None:
        parent = workflow.get_external_workflow_handle(input.owner_workflow_id)
        await parent.signal(
            QUESTIONNAIRE_FINISHED_SIGNAL_NAME,
            QuestionnaireFinishedSignal(questionnaire_key=input.questionnaire_key),
        )
        self._finished_signal_sent = True
        await workflow.wait_condition(lambda: self._released)


@workflow.defn(name=TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME, sandboxed=False)
class RecordingTelegramQuestionnaireWorkflow:
    def __init__(self) -> None:
        self._update_keys: list[str] = []

    @workflow.signal(name=QUESTIONNAIRE_UPDATE_SIGNAL_NAME)
    def accept_update(self, input: QuestionnaireUpdateSignal) -> None:
        self._update_keys.append(input.update_key)

    @workflow.query
    def received_update_keys(self) -> tuple[str, ...]:
        return tuple(self._update_keys)

    @workflow.run
    async def run(self, input: QuestionnaireWorkflowInput) -> None:
        await workflow.wait_condition(lambda: False)


@workflow.defn(name=TELEGRAM_SCREAM_WORKFLOW_NAME, sandboxed=False)
class FinishedTelegramScreamWorkflow:
    @workflow.run
    async def run(self, input: ScreamWorkflowInput) -> None:
        return None


class ActivityTranscript:
    def __init__(
        self,
        inspections: dict[str, InspectionKind],
        failing_inspection: str | None,
        failing_cleanup: bool,
        failing_response: str | None = None,
        blocked_inspection: str | None = None,
        failing_registration: bool = False,
        failing_mark_unreachable: bool = False,
        forbidden_delivery: str | None = None,
        quota_outcomes: list[object] | None = None,
        localization_required: bool = False,
        scream_requests: dict[str, ScreamRequest] | None = None,
        failing_custom_schedule: bool = False,
    ) -> None:
        self.inspections = inspections
        self.failing_inspection = failing_inspection
        self.failing_cleanup = failing_cleanup
        self.failing_response = failing_response
        self.blocked_inspection = blocked_inspection
        self.failing_registration = failing_registration
        self.failing_mark_unreachable = failing_mark_unreachable
        self.forbidden_delivery = forbidden_delivery
        self.quota_outcomes = list(quota_outcomes or [])
        self.localization_required = localization_required
        self.scream_requests = dict(scream_requests or {})
        self.failing_custom_schedule = failing_custom_schedule
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
            scream_request=self.scream_requests.get(input.update_key),
        )

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_help",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=PREPARE_LOCALIZATION_ACTIVITY_NAME)
    async def prepare_localization(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_localization",
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
        if input.update_key == self.failing_response:
            raise ApplicationError("response rejected", non_retryable=True)

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_group_unsupported",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=PREPARE_SCREAM_DENIED_ACTIVITY_NAME)
    async def prepare_scream_denied(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_scream_denied",
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

    @activity.defn(name=PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME)
    async def prepare_custom_notification(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="prepare_custom_notification",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME)
    async def generate_custom_notification_schedule(
        self,
        input: GenerateCustomNotificationScheduleInput,
    ) -> None:
        self.record(
            operation="generate_custom_notification_schedule",
            update_key=input.update_key,
            user_id=input.user_id,
        )
        if self.failing_custom_schedule:
            raise ApplicationError("schedule completion failed", non_retryable=True)

    @activity.defn(name=APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME)
    async def apply_custom_notification_schedule(
        self,
        input: ApplyCustomNotificationScheduleInput,
    ) -> None:
        self.record(
            operation="apply_custom_notification_schedule",
            update_key=input.proposal_key.removesuffix(":notification-schedule"),
            user_id=input.user_id,
        )

    @activity.defn(name=PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME)
    async def prepare_custom_notification_failure(
        self,
        input: PrepareCustomNotificationFailureInput,
    ) -> None:
        self.record(
            operation="prepare_custom_notification_failure",
            update_key=input.response_key.removesuffix(":response"),
            user_id=input.user_id,
        )

    @activity.defn(name=CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME)
    async def configure_notifications(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="configure_notifications",
            update_key=input.update_key,
            user_id=input.user_id,
        )

    @activity.defn(name=CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME)
    async def configure_localization(self, input: PrepareResponseInput) -> None:
        self.record(
            operation="configure_localization",
            update_key=input.update_key,
            user_id=input.user_id,
        )
        self.localization_required = False

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
    async def ensure_mortal(self, input: MortalActivityInput) -> MortalRegistration:
        if self.failing_registration:
            raise ApplicationError("PostgreSQL unavailable", non_retryable=True)
        return MortalRegistration(localization_required=self.localization_required)

    @activity.defn(name=MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME)
    async def mark_mortal_unreachable(self, input: MortalActivityInput) -> None:
        self.record(
            operation="mark_unreachable",
            update_key="mortal-lifecycle",
            user_id=input.mortal_id,
        )
        if self.failing_mark_unreachable:
            raise ApplicationError("reachability update unavailable", non_retryable=True)

    @activity.defn(name=CHECK_MORTAL_QUOTA_ACTIVITY_NAME)
    async def has_quota(self, input: MortalActivityInput) -> bool:
        outcome = self.quota_outcomes.pop(0) if self.quota_outcomes else True
        if isinstance(outcome, BaseException):
            raise outcome
        return bool(outcome)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.inspect,
            self.prepare_help,
            self.prepare_localization,
            self.prepare_unsupported,
            self.prepare_group_unsupported,
            self.prepare_scream_denied,
            self.prepare_limit_exhausted,
            self.prepare_custom_notification,
            self.generate_custom_notification_schedule,
            self.apply_custom_notification_schedule,
            self.prepare_custom_notification_failure,
            self.configure_notifications,
            self.configure_localization,
            self.deliver,
            self.cleanup,
            self.ensure_mortal,
            self.mark_mortal_unreachable,
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

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_help")(input)

    @activity.defn(name=PREPARE_LOCALIZATION_ACTIVITY_NAME)
    async def prepare_localization(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_localization")(input)

    @activity.defn(name=PREPARE_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_unsupported(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_unsupported")(input)

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_group_unsupported")(input)

    @activity.defn(name=PREPARE_SCREAM_DENIED_ACTIVITY_NAME)
    async def prepare_scream_denied(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_scream_denied")(input)

    @activity.defn(name=PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME)
    async def prepare_limit_exhausted(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_limit_exhausted")(input)

    @activity.defn(name=PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME)
    async def prepare_custom_notification(self, input: PrepareResponseInput) -> None:
        await self.selected("prepare_custom_notification")(input)

    @activity.defn(name=GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME)
    async def generate_custom_notification_schedule(
        self,
        input: GenerateCustomNotificationScheduleInput,
    ) -> None:
        await self.selected("generate_custom_notification_schedule")(input)

    @activity.defn(name=APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME)
    async def apply_custom_notification_schedule(
        self,
        input: ApplyCustomNotificationScheduleInput,
    ) -> None:
        await self.selected("apply_custom_notification_schedule")(input)

    @activity.defn(name=PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME)
    async def prepare_custom_notification_failure(
        self,
        input: PrepareCustomNotificationFailureInput,
    ) -> None:
        await self.selected("prepare_custom_notification_failure")(input)

    @activity.defn(name=CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME)
    async def configure_notifications(self, input: PrepareResponseInput) -> None:
        await self.selected("configure_notifications")(input)

    @activity.defn(name=CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME)
    async def configure_localization(self, input: PrepareResponseInput) -> None:
        await self.selected("configure_localization")(input)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        await self.selected("deliver")(input)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        await self.selected("cleanup")(input)

    @activity.defn(name=ENSURE_MORTAL_ACTIVITY_NAME)
    async def ensure_mortal(self, input: MortalActivityInput) -> MortalRegistration:
        return cast(MortalRegistration, await self.selected("ensure_mortal")(input))

    @activity.defn(name=MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME)
    async def mark_mortal_unreachable(self, input: MortalActivityInput) -> None:
        await self.selected("mark_mortal_unreachable")(input)

    @activity.defn(name=CHECK_MORTAL_QUOTA_ACTIVITY_NAME)
    async def has_quota(self, input: MortalActivityInput) -> bool:
        return cast(bool, await self.selected("has_quota")(input))

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.inspect,
            self.prepare_help,
            self.prepare_localization,
            self.prepare_unsupported,
            self.prepare_group_unsupported,
            self.prepare_scream_denied,
            self.prepare_limit_exhausted,
            self.prepare_custom_notification,
            self.generate_custom_notification_schedule,
            self.apply_custom_notification_schedule,
            self.prepare_custom_notification_failure,
            self.configure_notifications,
            self.configure_localization,
            self.deliver,
            self.cleanup,
            self.ensure_mortal,
            self.mark_mortal_unreachable,
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
        questionnaire_workflows = (
            TelegramQuestionnaireWorkflow,
            FailingTelegramQuestionnaireWorkflow,
            DelayedFailingTelegramQuestionnaireWorkflow,
            DelayedFinishedTelegramQuestionnaireWorkflow,
            RecordingTelegramQuestionnaireWorkflow,
        )
        for questionnaire_workflow in questionnaire_workflows:
            task_queue = f"deep-telegram-{uuid4()}"
            worker = Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[
                    TelegramUserWorkflow,
                    questionnaire_workflow,
                    FinishedTelegramScreamWorkflow,
                ],
                activities=activities.definitions(),
            )
            await worker.__aenter__()
            workers[questionnaire_workflow] = worker
            task_queues[questionnaire_workflow] = task_queue
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
        questionnaire_workflow: type,
    ) -> str:
        self.activities.use(activities)
        return self.task_queues[questionnaire_workflow]


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
        questionnaire_workflow: type = TelegramQuestionnaireWorkflow,
    ) -> WorkflowStory:
        task_queue = pool.select(
            activities=activities,
            questionnaire_workflow=questionnaire_workflow,
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
        "redis:text:1733": InspectionKind.TEXT,
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
        handle = await story.start("redis:text:1733", continue_after=None)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key="redis:text:1733"),
        )
        for key in ("redis:help:1741", "redis:unsupported:1747", "redis:group:1753"):
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=key),
            )
        await transcript.wait_for("cleanup", 4)

        assert transcript.events == [
            ("inspect", "redis:text:1733", 173_357),
            ("prepare_unsupported", "redis:text:1733", 173_357),
            ("deliver", "redis:text:1733", 173_357),
            ("cleanup", "redis:text:1733", 173_357),
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


async def test_denies_a_non_admin_scream_through_the_normal_response_pipeline(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:scream-denied:1754"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.SCREAM_DENIED},
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
        ("prepare_scream_denied", update_key, 173_357),
        ("deliver", update_key, 173_357),
        ("cleanup", update_key, 173_357),
    ], "non-admin scream bypassed denial or skipped ordinary payload cleanup"


async def test_rejects_an_unsupported_admin_scream_outside_questionnaire(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:scream-unsupported:17545"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.SCREAM_UNSUPPORTED},
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        await story.start(update_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)

    assert [event[0] for event in transcript.events] == [
        "inspect",
        "prepare_unsupported",
        "deliver",
        "cleanup",
    ], "unsupported admin scream started a broadcast or bypassed the standard response"


async def test_starts_an_abandoned_scream_child_for_an_admin_reply(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:scream-admin:1755"
    request = ScreamRequest(
        locale="en",
        source_chat_id=173_357,
        source_message_id=175_519,
    )
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.SCREAM},
        failing_inspection=None,
        failing_cleanup=False,
        scream_requests={update_key: request},
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        await story.start(update_key, continue_after=None)
        child = story.environment.client.get_workflow_handle(f"telegram-scream:{update_key}")
        async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
            while True:
                try:
                    await child.result()
                except RPCError as error:
                    if error.status is not RPCStatusCode.NOT_FOUND:
                        raise
                else:
                    break

    assert transcript.events == [("inspect", update_key, 173_357)], (
        "parent delivered, cleaned, or otherwise consumed a scream owned by its child"
    )


async def test_routes_commands_without_advancing_an_active_questionnaire(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-before-commands:1756"
    help_key = "redis:help-during-questionnaire:1757"
    unknown_key = "redis:unknown-command-during-questionnaire:1758"
    scream_key = "redis:scream-during-questionnaire:1759"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            help_key: InspectionKind.HELP,
            unknown_key: InspectionKind.UNSUPPORTED,
            scream_key: InspectionKind.SCREAM_UNSUPPORTED,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        questionnaire_workflow=RecordingTelegramQuestionnaireWorkflow,
    ) as story:
        handle = await story.start(begin_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        child = story.environment.client.get_workflow_handle(
            f"{handle.id}:questionnaire:{begin_key}"
        )
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=help_key),
        )
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=unknown_key),
        )
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=scream_key),
        )
        await transcript.wait_for("cleanup", 4)
        actual = await child.query("received_update_keys")

    assert (
        actual,
        [event[0] for event in transcript.events],
    ) == (
        [],
        [
            "inspect",
            "cleanup",
            "inspect",
            "prepare_help",
            "deliver",
            "cleanup",
            "inspect",
            "prepare_unsupported",
            "deliver",
            "cleanup",
            "inspect",
            "prepare_unsupported",
            "deliver",
            "cleanup",
        ],
    ), "a command reached the questionnaire or bypassed its parent-level response"


async def test_routes_notification_callback_without_entering_a_questionnaire(
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


async def test_custom_schedule_takes_one_text_without_advancing_questionnaire(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-before-custom-schedule:17571"
    callback_key = "redis:custom-schedule-callback:17573"
    schedule_key = "redis:custom-schedule-text:17579"
    answer_key = "redis:questionnaire-answer-after-custom:17581"
    stop_key = "redis:stop-after-custom-schedule:17583"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            callback_key: InspectionKind.CUSTOM_NOTIFICATION_SELECTION,
            schedule_key: InspectionKind.TEXT,
            answer_key: InspectionKind.TEXT,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        questionnaire_workflow=RecordingTelegramQuestionnaireWorkflow,
    ) as story:
        handle = await story.start(begin_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        for key in (callback_key, schedule_key, answer_key):
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=key),
            )
        await transcript.wait_for("cleanup", 3)
        await transcript.wait_for("inspect", 4)
        operations = [event[0] for event in transcript.events]
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert operations == [
        "inspect",
        "cleanup",
        "inspect",
        "prepare_custom_notification",
        "deliver",
        "cleanup",
        "inspect",
        "generate_custom_notification_schedule",
        "apply_custom_notification_schedule",
        "deliver",
        "cleanup",
        "inspect",
    ], "custom schedule text advanced the questionnaire or left custom mode active"


@pytest.mark.parametrize(
    ("quota_outcome", "failing_completion", "forbidden_delivery", "expected"),
    [
        (
            False,
            False,
            False,
            ["inspect", "prepare_limit", "deliver", "cleanup"],
        ),
        (
            True,
            True,
            False,
            [
                "inspect",
                "generate_custom_notification_schedule",
                "prepare_custom_notification_failure",
                "deliver",
                "cleanup",
            ],
        ),
        (
            ApplicationError("quota unavailable", non_retryable=True),
            False,
            False,
            ["inspect", "cleanup"],
        ),
        (
            True,
            False,
            True,
            [
                "inspect",
                "generate_custom_notification_schedule",
                "apply_custom_notification_schedule",
                "deliver",
                "mark_unreachable",
                "cleanup",
            ],
        ),
    ],
)
async def test_custom_schedule_handles_global_quota_or_completion_failure(
    quota_outcome: object,
    failing_completion: bool,
    forbidden_delivery: bool,
    expected: list[str],
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    callback_key = "redis:custom-schedule-callback:17587"
    schedule_key = "redis:custom-schedule-text:17589"
    stop_key = "redis:stop-after-custom-schedule-outcome:17591"
    transcript = ActivityTranscript(
        inspections={
            callback_key: InspectionKind.CUSTOM_NOTIFICATION_SELECTION,
            schedule_key: InspectionKind.TEXT,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
        quota_outcomes=[quota_outcome],
        failing_custom_schedule=failing_completion,
        forbidden_delivery=schedule_key if forbidden_delivery else None,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(callback_key, continue_after=1)
        await transcript.wait_for("cleanup", 1)
        transcript.events.clear()
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=schedule_key),
        )
        await transcript.wait_for("cleanup", 1)
        events = [event[0] for event in transcript.events]
        if forbidden_delivery:
            await handle.result()
        else:
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=stop_key),
            )
            await handle.result()

    assert events == expected


async def test_requires_localization_before_processing_a_new_mortal(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    first_key = "redis:first-contact:1758"
    selection_key = "redis:localization-selection:1759"
    text_key = "redis:text-after-localization:1763"
    stop_key = "redis:stop-after-localization:1769"
    transcript = ActivityTranscript(
        inspections={
            first_key: InspectionKind.TEXT,
            selection_key: InspectionKind.LOCALIZATION_SELECTION,
            text_key: InspectionKind.TEXT,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
        localization_required=True,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(first_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=selection_key),
        )
        await transcript.wait_for("cleanup", 2)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=text_key),
        )
        await transcript.wait_for("cleanup", 3)
        events = transcript.events[:12]
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert events == [
        ("inspect", first_key, 173_357),
        ("prepare_localization", first_key, 173_357),
        ("deliver", first_key, 173_357),
        ("cleanup", first_key, 173_357),
        ("inspect", selection_key, 173_357),
        ("configure_localization", selection_key, 173_357),
        ("deliver", selection_key, 173_357),
        ("cleanup", selection_key, 173_357),
        ("inspect", text_key, 173_357),
        ("prepare_unsupported", text_key, 173_357),
        ("deliver", text_key, 173_357),
        ("cleanup", text_key, 173_357),
    ], "first contact was processed before explicit localization or lost after selection"


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
        questionnaire_workflow=DelayedFailingTelegramQuestionnaireWorkflow,
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
async def test_does_not_restart_an_active_questionnaire_without_available_quota(
    second_quota: object,
    expected_operations: list[str],
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    first_key = "redis:begin-active-quota:first"
    second_key = "redis:begin-active-quota:second"
    stop_key = "redis:stop-after-active-quota:second"
    transcript = ActivityTranscript(
        inspections={
            first_key: InspectionKind.BEGIN,
            second_key: InspectionKind.BEGIN,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
        quota_outcomes=[True, second_quota],
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        questionnaire_workflow=DelayedFailingTelegramQuestionnaireWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(first_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=second_key),
            )
            await transcript.wait_for("cleanup", 2)
            operations = [event[0] for event in transcript.events]
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=stop_key),
            )
            await handle.result()

    assert operations == expected_operations


async def test_keeps_processing_after_activity_and_cleanup_failures(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:fractured:1759": InspectionKind.TEXT,
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
    failed_key = "redis:response-failure:1779"
    survivor_key = "redis:response-survivor:1781"
    stop_key = "redis:stop-after-response-survivor:1782"
    transcript = ActivityTranscript(
        inspections={
            failed_key: InspectionKind.TEXT,
            survivor_key: InspectionKind.HELP,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
        failing_response=failed_key,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(failed_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=survivor_key),
        )
        await transcript.wait_for("cleanup", 2)
        events = transcript.events[:5]
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert events == [
        ("inspect", failed_key, 173_357),
        ("prepare_unsupported", failed_key, 173_357),
        ("cleanup", failed_key, 173_357),
        ("inspect", survivor_key, 173_357),
        ("prepare_help", survivor_key, 173_357),
    ], "failed response preparation terminated the per-user workflow"


async def test_recovers_when_a_child_questionnaire_workflow_fails(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-failed-child:1783"
    text_key = "redis:text-after-failed-child:1787"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            text_key: InspectionKind.TEXT,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        questionnaire_workflow=FailingTelegramQuestionnaireWorkflow,
    ) as story:
        handle = await story.start(begin_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        child_id = f"{handle.id}:questionnaire:{begin_key}"
        child = story.environment.client.get_workflow_handle(child_id)
        with pytest.raises(WorkflowFailureError):
            await child.result()
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=text_key),
        )
        await transcript.wait_for("cleanup", 2)

        assert transcript.events[-4:] == [
            ("inspect", text_key, 173_357),
            ("prepare_unsupported", text_key, 173_357),
            ("deliver", text_key, 173_357),
            ("cleanup", text_key, 173_357),
        ], "failed child questionnaire prevented later updates from using normal routing"


async def test_reroutes_an_update_when_child_fails_during_inspection(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-delayed-failure:1789"
    text_key = "redis:text-during-child-failure:1801"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            text_key: InspectionKind.TEXT,
        },
        failing_inspection=None,
        failing_cleanup=False,
        blocked_inspection=text_key,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        questionnaire_workflow=DelayedFailingTelegramQuestionnaireWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(begin_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=text_key),
            )
            await asyncio.wait_for(
                transcript.inspection_started.wait(),
                timeout=TEST_TIMEOUT_SECONDS,
            )
            child_id = f"{handle.id}:questionnaire:{begin_key}"
            child = story.environment.client.get_workflow_handle(child_id)
            await child.signal("release_failure")
            with pytest.raises(WorkflowFailureError):
                await child.result()
            transcript.release_inspection.set()
            await transcript.wait_for("cleanup", 2)

        assert transcript.events[-4:] == [
            ("inspect", text_key, 173_357),
            ("prepare_unsupported", text_key, 173_357),
            ("deliver", text_key, 173_357),
            ("cleanup", text_key, 173_357),
        ], "update inspected during child failure was not rerouted to normal text processing"


async def test_carries_deduplication_state_through_continue_as_new(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:first:1783": InspectionKind.TEXT,
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
    stop_key = "telegram:updates:1801:stop-after-history-check"
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
        update_reader=telegram.update_documents,
        logger=SilentLogger(),
    )
    prepare = PrepareTelegramResponseActivities(
        response_store=telegram.response_documents,
        ttl_seconds=1801,
        content=BotContents.debug(),
        mortals=MortalMemory({173_357: Mortal(id=173_357)}),
        logger=SilentLogger(),
    )
    deliver = DeliverTelegramResponseActivity(
        response_reader=telegram.response_documents,
        sender=telegram,
        logger=SilentLogger(),
    )
    cleanup = CleanupTelegramPayloadsActivity(
        cleaner=telegram,
        logger=SilentLogger(),
    )
    lifecycle = ActivityTranscript(
        inspections={},
        failing_inspection=None,
        failing_cleanup=False,
    )
    definitions: Sequence[Callable[..., object]] = [
        inspect.inspect,
        prepare.prepare_help,
        prepare.prepare_unsupported,
        prepare.prepare_group_unsupported,
        deliver.deliver,
        cleanup.cleanup,
        lifecycle.ensure_mortal,
        lifecycle.mark_mortal_unreachable,
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
        telegram.update_result = TelegramUpdates.membership(
            update_id=1801,
            user_id=173_357,
            bot_id=180_107,
            old_status="member",
            new_status="kicked",
        )
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert (
        (
            "send_text",
            179_297,
            "Use /help to learn how to use the bot",
        )
        in telegram.events,
        all(secret not in str(event) for event in telegram.events),
        secret not in json.dumps(history.to_json_dict()),
    ) == (True, True, True), "plain text was returned or persisted in Temporal history"


async def test_skips_processing_when_mortal_registration_fails(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:registration-failure:1811"
    stop_key = "redis:stop-after-registration-failure:1812"
    transcript = ActivityTranscript(
        inspections={
            update_key: InspectionKind.TEXT,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
        failing_registration=True,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(update_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        operations = [event[0] for event in transcript.events]
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert operations == [
        "inspect",
        "cleanup",
    ], "response pipeline ran without a successfully registered Mortal"


async def test_unblock_registers_silently_before_later_text(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    unblock_key = "redis:unblocked:1823"
    text_key = "redis:text-after-unblock:1831"
    stop_key = "redis:stop-after-unblock:1832"
    transcript = ActivityTranscript(
        inspections={
            unblock_key: InspectionKind.MORTAL_UNBLOCKED,
            text_key: InspectionKind.TEXT,
            stop_key: InspectionKind.MORTAL_BLOCKED,
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
            TelegramUpdateSignal(redis_key=text_key),
        )
        await transcript.wait_for("cleanup", 2)
        events = list(transcript.events)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert events == [
        ("inspect", unblock_key, 173_357),
        ("cleanup", unblock_key, 173_357),
        ("inspect", text_key, 173_357),
        ("prepare_unsupported", text_key, 173_357),
        ("deliver", text_key, 173_357),
        ("cleanup", text_key, 173_357),
    ], "unblock produced a Telegram response or failed to restore normal routing"


async def test_unblock_stays_silent_when_reactivation_fails(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    unblock_key = "redis:unblock-reactivation-failure:1837"
    stop_key = "redis:stop-after-unblock-reactivation-failure:1838"
    transcript = ActivityTranscript(
        inspections={
            unblock_key: InspectionKind.MORTAL_UNBLOCKED,
            stop_key: InspectionKind.MORTAL_BLOCKED,
        },
        failing_inspection=None,
        failing_cleanup=False,
        failing_registration=True,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
    ) as story:
        handle = await story.start(unblock_key, continue_after=None)
        await transcript.wait_for("cleanup", 1)
        events = list(transcript.events)
        await handle.signal(
            TELEGRAM_UPDATE_SIGNAL_NAME,
            TelegramUpdateSignal(redis_key=stop_key),
        )
        await handle.result()

    assert events == [
        ("inspect", unblock_key, 173_357),
        ("cleanup", unblock_key, 173_357),
    ], "failed unblock reactivation leaked a response or entered ordinary processing"


@pytest.mark.parametrize("failing_mark_unreachable", [False, True])
async def test_block_marks_the_mortal_unreachable_and_completes_parent(
    failing_mark_unreachable: bool,
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:blocked:1847"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.MORTAL_BLOCKED},
        failing_inspection=None,
        failing_cleanup=False,
        failing_mark_unreachable=failing_mark_unreachable,
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
        ("mark_unreachable", "mortal-lifecycle", 173_357),
    ], "block update did not clean Redis, mark the Mortal unreachable, and stop its parent"


async def test_forbidden_delivery_marks_unreachable_and_completes_parent(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    update_key = "redis:forbidden:1861"
    transcript = ActivityTranscript(
        inspections={update_key: InspectionKind.TEXT},
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
        "prepare_unsupported",
        "deliver",
        "mark_unreachable",
        "cleanup",
    ], "Telegram Forbidden did not mark the Mortal unreachable before parent completion"


async def test_block_cancels_an_active_questionnaire_before_marking_unreachable(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-before-block:1867"
    blocked_key = "redis:block-during-questionnaire:1871"
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
        questionnaire_workflow=DelayedFailingTelegramQuestionnaireWorkflow,
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
        "mark_unreachable",
    ], "block left an active questionnaire child or skipped the reachability update"


async def test_waits_for_a_finished_child_before_routing_the_next_update(
    workflow_worker_pool: WorkflowWorkerPool,
) -> None:
    begin_key = "redis:begin-finishing-child:1873"
    text_key = "redis:text-after-finished-signal:1877"
    transcript = ActivityTranscript(
        inspections={
            begin_key: InspectionKind.BEGIN,
            text_key: InspectionKind.TEXT,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(
        pool=workflow_worker_pool,
        activities=transcript.definitions(),
        questionnaire_workflow=DelayedFinishedTelegramQuestionnaireWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(begin_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            child_id = f"{handle.id}:questionnaire:{begin_key}"
            child = story.environment.client.get_workflow_handle(child_id)
            async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
                while not await child.query("finished_signal_sent"):
                    pass
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=text_key),
            )
            await child.signal("release_completion")
            await transcript.wait_for("cleanup", 2)

    assert transcript.events[-4:] == [
        ("inspect", text_key, 173_357),
        ("prepare_unsupported", text_key, 173_357),
        ("deliver", text_key, 173_357),
        ("cleanup", text_key, 173_357),
    ], "parent routed an update into a child that had stopped accepting signals"
