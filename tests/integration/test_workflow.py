import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import timedelta
from types import TracebackType
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from sein_zum_tode.bot.activities import (
    CleanupTelegramPayloadsActivity,
    DeliverTelegramResponseActivity,
    InspectTelegramUpdateActivity,
    PrepareTelegramResponseActivities,
)
from sein_zum_tode.bot.conversation.models import (
    TELEGRAM_CONVERSATION_WORKFLOW_NAME,
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
    PREPARE_UNSUPPORTED_ACTIVITY_NAME,
    TELEGRAM_UPDATE_SIGNAL_NAME,
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
from tests.support import SilentLogger, TelegramMemory, TelegramUpdates

pytestmark = pytest.mark.deep


@workflow.defn(name=TELEGRAM_CONVERSATION_WORKFLOW_NAME)
class FailingTelegramConversationWorkflow:
    @workflow.run
    async def run(self, input: ConversationWorkflowInput) -> None:
        raise ApplicationError("conversation workflow failed", non_retryable=True)


@workflow.defn(name=TELEGRAM_CONVERSATION_WORKFLOW_NAME)
class DelayedFailingTelegramConversationWorkflow:
    @workflow.run
    async def run(self, input: ConversationWorkflowInput) -> None:
        await workflow.sleep(timedelta(seconds=2))
        raise ApplicationError("conversation workflow failed", non_retryable=True)


class ActivityTranscript:
    def __init__(
        self,
        inspections: dict[str, InspectionKind],
        failing_inspection: str | None,
        failing_cleanup: bool,
        failing_response: str | None = None,
        blocked_inspection: str | None = None,
    ) -> None:
        self.inspections = inspections
        self.failing_inspection = failing_inspection
        self.failing_cleanup = failing_cleanup
        self.failing_response = failing_response
        self.blocked_inspection = blocked_inspection
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

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        self.record(
            operation="deliver",
            update_key=input.update_key or "missing-update-key",
            user_id=input.user_id,
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

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.inspect,
            self.prepare_echo,
            self.prepare_help,
            self.prepare_unsupported,
            self.prepare_group_unsupported,
            self.deliver,
            self.cleanup,
        ]

    async def wait_for(self, operation: str, count: int) -> None:
        while sum(event[0] == operation for event in self.events) < count:
            self.changed.clear()
            await asyncio.wait_for(self.changed.wait(), timeout=7)


class WorkflowStory:
    def __init__(
        self,
        environment: WorkflowEnvironment,
        worker: Worker,
        task_queue: str,
    ) -> None:
        self.environment = environment
        self.worker = worker
        self.task_queue = task_queue
        self.handles: list[WorkflowHandle] = []

    @classmethod
    async def open(
        cls,
        activities: Sequence[Callable[..., object]],
        *,
        conversation_workflow: type = TelegramConversationWorkflow,
    ) -> WorkflowStory:
        environment = await WorkflowEnvironment.start_time_skipping()
        task_queue = f"deep-telegram-{uuid4()}"
        worker = Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramUserWorkflow, conversation_workflow],
            activities=activities,
        )
        await worker.__aenter__()
        return cls(
            environment=environment,
            worker=worker,
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
            await handle.cancel()
        await self.worker.__aexit__(exception_type, exception, traceback)
        await self.environment.shutdown()

    async def start(
        self,
        update_key: str,
        *,
        continue_after: int | None,
    ) -> WorkflowHandle:
        handle = await self.environment.client.start_workflow(
            TelegramUserWorkflow.run,
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

    async def wait_for_new_run(self, handle: WorkflowHandle, previous_run: str) -> str:
        async with asyncio.timeout(7):
            while True:
                current = (
                    await handle.describe()
                ).raw_description.workflow_execution_info.execution.run_id
                if current != previous_run:
                    return current
                await asyncio.sleep(0)


async def test_routes_unique_signals_through_the_complete_pipeline() -> None:
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
    async with await WorkflowStory.open(transcript.definitions()) as story:
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


async def test_keeps_processing_after_activity_and_cleanup_failures() -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:fractured:1759": InspectionKind.ECHO,
            "redis:survivor:1777": InspectionKind.HELP,
        },
        failing_inspection="redis:fractured:1759",
        failing_cleanup=True,
    )
    async with await WorkflowStory.open(transcript.definitions()) as story:
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


async def test_keeps_processing_after_response_preparation_failure() -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:response-failure:1779": InspectionKind.ECHO,
            "redis:response-survivor:1781": InspectionKind.HELP,
        },
        failing_inspection=None,
        failing_cleanup=False,
        failing_response="redis:response-failure:1779",
    )
    async with await WorkflowStory.open(transcript.definitions()) as story:
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


async def test_recovers_when_a_child_conversation_workflow_fails() -> None:
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
        transcript.definitions(),
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


async def test_reroutes_an_update_when_child_fails_during_inspection() -> None:
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
        transcript.definitions(),
        conversation_workflow=DelayedFailingTelegramConversationWorkflow,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(begin_key, continue_after=None)
            await transcript.wait_for("cleanup", 1)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=echo_key),
            )
            await asyncio.wait_for(transcript.inspection_started.wait(), timeout=7)
            await story.environment.sleep(timedelta(seconds=3))
            child_id = f"{handle.id}:conversation:{begin_key}"
            child = story.environment.client.get_workflow_handle(child_id)
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


async def test_carries_deduplication_state_through_continue_as_new() -> None:
    transcript = ActivityTranscript(
        inspections={
            "redis:first:1783": InspectionKind.ECHO,
            "redis:second:1787": InspectionKind.HELP,
        },
        failing_inspection=None,
        failing_cleanup=False,
    )
    async with await WorkflowStory.open(transcript.definitions()) as story:
        handle = await story.start("redis:first:1783", continue_after=1)
        first_run = handle.first_execution_run_id
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


async def test_keeps_sensitive_message_text_out_of_workflow_history() -> None:
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
        help_text="Navigate by the constellations",
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
    definitions = [
        inspect.inspect,
        prepare.prepare_echo,
        prepare.prepare_help,
        prepare.prepare_unsupported,
        prepare.prepare_group_unsupported,
        deliver.deliver,
        cleanup.cleanup,
    ]
    async with await WorkflowStory.open(definitions) as story:
        handle = await story.start("telegram:updates:1801:1789", continue_after=None)
        await asyncio.wait_for(telegram.sent.wait(), timeout=7)
        history = await handle.fetch_history()

        assert (
            ("send_text", 179_297, secret) in telegram.events,
            secret not in json.dumps(history.to_json_dict()),
        ) == (True, True), "Temporal persisted sensitive text or delivery changed it"
