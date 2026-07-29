import asyncio
import json
from collections.abc import Callable
from uuid import uuid4

from aiogram.types import Update
from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.exceptions import ApplicationError
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
    TelegramResponse,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.bot.workflow import TelegramUserWorkflow


class RecordingActivities:
    def __init__(
        self,
        inspections: dict[str, InspectionKind],
        *,
        inspect_failure_key: str | None = None,
        cleanup_failure: bool = False,
    ) -> None:
        self.inspections = inspections
        self.inspect_failure_key = inspect_failure_key
        self.cleanup_failure = cleanup_failure
        self.calls: list[tuple[str, str]] = []
        self.changed = asyncio.Event()

    @activity.defn(name=INSPECT_UPDATE_ACTIVITY_NAME)
    async def inspect(self, input: InspectUpdateInput) -> InspectedUpdate:
        self.calls.append(("inspect", input.update_key))
        self.changed.set()
        if input.update_key == self.inspect_failure_key:
            raise ApplicationError("inspection failed", non_retryable=True)
        return InspectedUpdate(
            kind=self.inspections[input.update_key],
            update_key=input.update_key,
            chat_id=input.user_id,
        )

    @activity.defn(name=PREPARE_ECHO_ACTIVITY_NAME)
    async def prepare_echo(self, input: PrepareResponseInput) -> None:
        assert input.user_id == 40
        self._record("prepare_echo", input.update_key)

    @activity.defn(name=PREPARE_HELP_ACTIVITY_NAME)
    async def prepare_help(self, input: PrepareResponseInput) -> None:
        assert input.user_id == 40
        self._record("prepare_help", input.update_key)

    @activity.defn(name=PREPARE_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_unsupported(self, input: PrepareResponseInput) -> None:
        assert input.user_id == 40
        self._record("prepare_unsupported", input.update_key)

    @activity.defn(name=PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME)
    async def prepare_group_unsupported(self, input: PrepareResponseInput) -> None:
        assert input.user_id == 40
        self._record("prepare_group_unsupported", input.update_key)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        assert input.user_id == 40
        assert input.update_key is not None
        self._record("deliver", input.response_key.removesuffix(":response"))

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        assert input.user_id == 40
        assert input.update_key is not None
        update_key = input.keys[0]
        self._record("cleanup", update_key)
        if self.cleanup_failure:
            raise ApplicationError("cleanup failed", non_retryable=True)

    def activities(self) -> list[Callable[..., object]]:
        return [
            self.inspect,
            self.prepare_echo,
            self.prepare_help,
            self.prepare_unsupported,
            self.prepare_group_unsupported,
            self.deliver,
            self.cleanup,
        ]

    def _record(self, operation: str, update_key: str) -> None:
        self.calls.append((operation, update_key))
        self.changed.set()

    async def wait_for(self, predicate: Callable[[], bool]) -> None:
        while not predicate():
            self.changed.clear()
            await asyncio.wait_for(self.changed.wait(), timeout=10)


async def start_workflow(
    environment: WorkflowEnvironment,
    task_queue: str,
    input: UserWorkflowInput,
    update_key: str,
) -> WorkflowHandle:
    return await environment.client.start_workflow(
        TelegramUserWorkflow.run,
        input,
        id=f"test-user-{uuid4()}",
        task_queue=task_queue,
        start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
        start_signal_args=[TelegramUpdateSignal(update_key)],
    )


async def test_workflow_uses_selected_prepare_activities_and_deduplicates() -> None:
    environment = await WorkflowEnvironment.start_time_skipping()
    task_queue = str(uuid4())
    kinds = {
        "echo": InspectionKind.ECHO,
        "help": InspectionKind.HELP,
        "unsupported": InspectionKind.UNSUPPORTED,
        "group": InspectionKind.GROUP_UNSUPPORTED,
    }
    recording = RecordingActivities(kinds)
    try:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramUserWorkflow],
            activities=recording.activities(),
        ):
            handle = await start_workflow(
                environment,
                task_queue,
                UserWorkflowInput(user_id=40, activity_retry_timeout_seconds=2),
                "echo",
            )
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal("echo"),
            )
            for key in ("help", "unsupported", "group"):
                await handle.signal(
                    TELEGRAM_UPDATE_SIGNAL_NAME,
                    TelegramUpdateSignal(key),
                )
            await recording.wait_for(
                lambda: sum(call[0] == "cleanup" for call in recording.calls) == 4
            )

            assert recording.calls == [
                ("inspect", "echo"),
                ("prepare_echo", "echo"),
                ("deliver", "echo"),
                ("cleanup", "echo"),
                ("inspect", "help"),
                ("prepare_help", "help"),
                ("deliver", "help"),
                ("cleanup", "help"),
                ("inspect", "unsupported"),
                ("prepare_unsupported", "unsupported"),
                ("deliver", "unsupported"),
                ("cleanup", "unsupported"),
                ("inspect", "group"),
                ("prepare_group_unsupported", "group"),
                ("deliver", "group"),
                ("cleanup", "group"),
            ]
            await handle.cancel()
    finally:
        await environment.shutdown()


async def test_workflow_cleans_up_after_processing_and_cleanup_failures() -> None:
    environment = await WorkflowEnvironment.start_time_skipping()
    task_queue = str(uuid4())
    recording = RecordingActivities(
        {"inspect-fails": InspectionKind.ECHO, "next": InspectionKind.HELP},
        inspect_failure_key="inspect-fails",
        cleanup_failure=True,
    )
    try:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramUserWorkflow],
            activities=recording.activities(),
        ):
            handle = await start_workflow(
                environment,
                task_queue,
                UserWorkflowInput(user_id=40, activity_retry_timeout_seconds=2),
                "inspect-fails",
            )
            await recording.wait_for(lambda: ("cleanup", "inspect-fails") in recording.calls)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal("next"),
            )
            await recording.wait_for(lambda: ("inspect", "next") in recording.calls)

            assert ("prepare_echo", "inspect-fails") not in recording.calls
            await handle.cancel()
    finally:
        await environment.shutdown()


async def test_workflow_continues_as_new_and_carries_deduplication_state() -> None:
    environment = await WorkflowEnvironment.start_time_skipping()
    task_queue = str(uuid4())
    recording = RecordingActivities({"first": InspectionKind.ECHO, "second": InspectionKind.HELP})
    try:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramUserWorkflow],
            activities=recording.activities(),
        ):
            handle = await start_workflow(
                environment,
                task_queue,
                UserWorkflowInput(
                    user_id=40,
                    activity_retry_timeout_seconds=2,
                    continue_as_new_after_updates=1,
                ),
                "first",
            )
            first_run_id = handle.first_execution_run_id
            await recording.wait_for(lambda: ("cleanup", "first") in recording.calls)

            async def current_run_id() -> str:
                description = await handle.describe()
                return description.raw_description.workflow_execution_info.execution.run_id

            for _ in range(100):
                if await current_run_id() != first_run_id:
                    break
                await asyncio.sleep(0.01)
            assert await current_run_id() != first_run_id

            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal("first"),
            )
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal("second"),
            )
            await recording.wait_for(lambda: ("cleanup", "second") in recording.calls)

            assert recording.calls.count(("inspect", "first")) == 1
            await handle.cancel()
    finally:
        await environment.shutdown()


class InMemoryTelegram:
    def __init__(self, update: Update) -> None:
        self.update = update
        self.responses: dict[str, TelegramResponse] = {}
        self.sent: list[TelegramResponse] = []
        self.delivered = asyncio.Event()

    async def load_update(self, key: str) -> Update | None:
        return self.update

    async def store_response(
        self,
        key: str,
        response: TelegramResponse,
        ttl_seconds: int,
    ) -> None:
        self.responses[key] = response

    async def load_response(self, key: str) -> TelegramResponse | None:
        return self.responses.get(key)

    async def delete(self, keys: tuple[str, ...]) -> None:
        for key in keys:
            self.responses.pop(key, None)

    async def send_text(self, chat_id: int, text: str) -> None:
        self.sent.append(TelegramResponse(chat_id=chat_id, text=text))
        self.delivered.set()


async def test_workflow_history_does_not_contain_sensitive_payload(
    make_update: Callable[[int, str], Update],
) -> None:
    secret = "history-must-not-contain-this-secret"
    telegram = InMemoryTelegram(make_update(17, secret))
    inspect = InspectTelegramUpdateActivity(telegram)
    prepare = PrepareTelegramResponseActivities(
        telegram,
        telegram,
        ttl_seconds=600,
    )
    deliver = DeliverTelegramResponseActivity(telegram, telegram)
    cleanup = CleanupTelegramPayloadsActivity(telegram)
    environment = await WorkflowEnvironment.start_time_skipping()
    task_queue = str(uuid4())
    try:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramUserWorkflow],
            activities=[
                inspect.inspect,
                prepare.prepare_echo,
                prepare.prepare_help,
                prepare.prepare_unsupported,
                prepare.prepare_group_unsupported,
                deliver.deliver,
                cleanup.cleanup,
            ],
        ):
            handle = await start_workflow(
                environment,
                task_queue,
                UserWorkflowInput(user_id=40, activity_retry_timeout_seconds=2),
                "telegram:updates:42:17",
            )
            await asyncio.wait_for(telegram.delivered.wait(), timeout=10)
            history = await handle.fetch_history()

            assert telegram.sent == [TelegramResponse(chat_id=30, text=secret)]
            assert secret not in json.dumps(history.to_json_dict())
            await handle.cancel()
    finally:
        await environment.shutdown()
