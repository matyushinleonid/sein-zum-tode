import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import timedelta
from types import TracebackType
from typing import cast
from uuid import uuid4

import pytest
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
from sein_zum_tode.bot.conversation.activities import (
    RecordTelegramConversationAnswerActivity,
    StartTelegramConversationActivity,
)
from sein_zum_tode.bot.conversation.models import (
    CONVERSATION_UPDATE_SIGNAL_NAME,
    RECORD_CONVERSATION_ANSWER_ACTIVITY_NAME,
    START_CONVERSATION_ACTIVITY_NAME,
    ConversationStarted,
    ConversationTurn,
    ConversationTurnKind,
    ConversationUpdateSignal,
    ConversationWorkflowInput,
    RecordConversationAnswerInput,
    StartConversationInput,
)
from sein_zum_tode.bot.conversation.workflow import TelegramConversationWorkflow
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    TELEGRAM_UPDATE_SIGNAL_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from tests.support import BotContents, ConversationMemory, SilentLogger, TelegramUpdates

pytestmark = pytest.mark.deep


class ConversationActivityTranscript:
    def __init__(
        self,
        *,
        start_outcome: object,
        turn_outcomes: dict[str, object],
        failed_deliveries: set[str] | None = None,
        fail_cleanup: bool = False,
        blocked_updates: set[str] | None = None,
    ) -> None:
        self.start_outcome = start_outcome
        self.turn_outcomes = turn_outcomes
        self.failed_deliveries = failed_deliveries or set()
        self.fail_cleanup = fail_cleanup
        self.blocked_updates = blocked_updates or set()
        self.events: list[tuple[object, ...]] = []
        self.changed = asyncio.Event()
        self.record_started = asyncio.Event()
        self.release_record = asyncio.Event()

    def record_event(self, *event: object) -> None:
        self.events.append(event)
        self.changed.set()

    @activity.defn(name=START_CONVERSATION_ACTIVITY_NAME)
    async def start(self, input: StartConversationInput) -> ConversationStarted:
        self.record_event("start", input.conversation_key)
        if isinstance(self.start_outcome, BaseException):
            raise self.start_outcome
        return cast(ConversationStarted, self.start_outcome)

    @activity.defn(name=RECORD_CONVERSATION_ANSWER_ACTIVITY_NAME)
    async def record(self, input: RecordConversationAnswerInput) -> ConversationTurn:
        self.record_event("record", input.update_key)
        if input.update_key in self.blocked_updates:
            self.record_started.set()
            await self.release_record.wait()
        outcome = self.turn_outcomes[input.update_key]
        if isinstance(outcome, BaseException):
            raise outcome
        return cast(ConversationTurn, outcome)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        self.record_event("deliver", input.response_key)
        if input.response_key in self.failed_deliveries:
            raise ApplicationError("delivery rejected", non_retryable=True)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        self.record_event("cleanup", input.keys)
        if self.fail_cleanup:
            raise ApplicationError("cleanup rejected", non_retryable=True)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.start,
            self.record,
            self.deliver,
            self.cleanup,
        ]

    async def wait_for(self, operation: str, count: int) -> None:
        while sum(event[0] == operation for event in self.events) < count:
            self.changed.clear()
            await asyncio.wait_for(self.changed.wait(), timeout=7)


class FaultConversationWorkflowStory:
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
        self.handles: list[WorkflowHandle] = []

    @classmethod
    async def open(
        cls,
        activities: Sequence[Callable[..., object]],
    ) -> FaultConversationWorkflowStory:
        environment = await WorkflowEnvironment.start_time_skipping()
        task_queue = f"fault-conversation-{uuid4()}"
        worker = Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramConversationWorkflow],
            activities=activities,
        )
        await worker.__aenter__()
        return cls(
            environment=environment,
            worker=worker,
            task_queue=task_queue,
        )

    async def __aenter__(self) -> FaultConversationWorkflowStory:
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

    async def start(self) -> WorkflowHandle:
        handle = await self.environment.client.start_workflow(
            TelegramConversationWorkflow.run,
            ConversationWorkflowInput(
                conversation_key="telegram:conversation:fault:2401",
                user_id=240_103,
                chat_id=240_109,
                inactivity_timeout_seconds=300,
                activity_retry_timeout_seconds=7,
            ),
            id=f"fault-conversation-{uuid4()}",
            task_queue=self.task_queue,
        )
        self.handles.append(handle)
        return handle


class ConversationWorkflowStory:
    def __init__(
        self,
        *,
        environment: WorkflowEnvironment,
        worker: Worker,
        task_queue: str,
        memory: ConversationMemory,
        inactivity_timeout_seconds: int,
    ) -> None:
        self.environment = environment
        self.worker = worker
        self.task_queue = task_queue
        self.memory = memory
        self.inactivity_timeout_seconds = inactivity_timeout_seconds
        self.handles: list[WorkflowHandle] = []

    @classmethod
    async def open(
        cls,
        *,
        memory: ConversationMemory,
        inactivity_timeout_seconds: int,
    ) -> ConversationWorkflowStory:
        environment = await WorkflowEnvironment.start_time_skipping()
        task_queue = f"deep-conversation-{uuid4()}"
        content = BotContents.debug()
        inspect = InspectTelegramUpdateActivity(
            update_reader=memory,
            logger=SilentLogger(),
        )
        prepare = PrepareTelegramResponseActivities(
            update_reader=memory,
            response_store=memory,
            ttl_seconds=211,
            help_text=content.default().help,
            logger=SilentLogger(),
        )
        start = StartTelegramConversationActivity(
            content=content,
            conversations=memory,
            responses=memory,
            conversation_ttl_seconds=inactivity_timeout_seconds,
            response_ttl_seconds=211,
            privacy_response_ttl_seconds=inactivity_timeout_seconds + 7,
            logger=SilentLogger(),
        )
        record = RecordTelegramConversationAnswerActivity(
            updates=memory,
            conversations=memory,
            responses=memory,
            conversation_ttl_seconds=inactivity_timeout_seconds,
            response_ttl_seconds=211,
            privacy_response_ttl_seconds=inactivity_timeout_seconds + 7,
            logger=SilentLogger(),
        )
        deliver = DeliverTelegramResponseActivity(
            response_reader=memory,
            sender=memory,
            logger=SilentLogger(),
        )
        cleanup = CleanupTelegramPayloadsActivity(
            cleaner=memory,
            logger=SilentLogger(),
        )
        worker = Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramUserWorkflow, TelegramConversationWorkflow],
            activities=[
                inspect.inspect,
                prepare.prepare_echo,
                prepare.prepare_help,
                prepare.prepare_unsupported,
                prepare.prepare_group_unsupported,
                start.start,
                record.record,
                deliver.deliver,
                cleanup.cleanup,
            ],
        )
        await worker.__aenter__()
        return cls(
            environment=environment,
            worker=worker,
            task_queue=task_queue,
            memory=memory,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
        )

    async def __aenter__(self) -> ConversationWorkflowStory:
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

    async def start(self, begin_key: str) -> WorkflowHandle:
        handle = await self.environment.client.start_workflow(
            TelegramUserWorkflow.run,
            UserWorkflowInput(
                user_id=241_103,
                activity_retry_timeout_seconds=7,
                conversation_ttl_seconds=self.inactivity_timeout_seconds,
            ),
            id=f"deep-conversation-user-{uuid4()}",
            task_queue=self.task_queue,
            start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
            start_signal_args=[TelegramUpdateSignal(redis_key=begin_key)],
        )
        self.handles.append(handle)
        return handle


def private_message(*, update_id: int, text: str) -> object:
    return TelegramUpdates.message(
        update_id=update_id,
        user_id=241_103,
        chat_id=241_109,
        text=text,
        chat_type="private",
    )


async def test_runs_the_complete_private_questionnaire_without_persisting_answers() -> None:
    begin_key = "telegram:update:begin:2411"
    first_answer_key = "telegram:update:answer:2417"
    second_answer_key = "telegram:update:answer:2423"
    echo_key = "telegram:update:echo:2437"
    first_secret = "Sensitive first answer 2417"
    second_secret = "Sensitive second answer 2423"
    memory = ConversationMemory(
        updates={
            begin_key: private_message(update_id=2411, text="/begin"),
            first_answer_key: private_message(update_id=2417, text=first_secret),
            second_answer_key: private_message(update_id=2423, text=second_secret),
            echo_key: private_message(update_id=2437, text="Echo after completion"),
        }
    )
    async with await ConversationWorkflowStory.open(
        memory=memory,
        inactivity_timeout_seconds=300,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(begin_key)
            await memory.wait_for_messages(2)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=first_answer_key),
            )
            await memory.wait_for_messages(3)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=second_answer_key),
            )
            await memory.wait_for_messages(5)
            await memory.wait_until_absent(f"{begin_key}:conversation:privacy")
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=echo_key),
            )
            await memory.wait_for_messages(6)
            await memory.wait_until_absent(f"{echo_key}:response")
            child_id = f"{handle.id}:conversation:{begin_key}"
            parent_history = await handle.fetch_history()
            child_history = await story.environment.client.get_workflow_handle(
                child_id
            ).fetch_history()

        histories = json.dumps(
            [
                parent_history.to_json_dict(),
                child_history.to_json_dict(),
            ]
        )
        assert memory.messages == [
            (241_109, "mock conversation started"),
            (241_109, "q1?"),
            (241_109, "q2?"),
            (
                241_109,
                "thanks for your answers! "
                "[{'question_id': 'q1', 'question': 'q1?', "
                f"'answer': '{first_secret}'"
                "}, {'question_id': 'q2', 'question': 'q2?', "
                f"'answer': '{second_secret}'"
                "}]",
            ),
            (241_109, "your answers were deleted from our system"),
            (241_109, "Echo after completion"),
        ], "parent and child Workflows did not execute the configured conversation in order"
        assert (
            memory.conversations,
            memory.responses,
            first_answer_key in memory.updates,
            second_answer_key in memory.updates,
            echo_key in memory.updates,
            first_secret not in histories,
            second_secret not in histories,
        ) == (
            {},
            {},
            False,
            False,
            False,
            True,
            True,
        ), "completion retained private Redis data or persisted answers in Temporal history"


async def test_deletes_an_inactive_conversation_and_notifies_the_user() -> None:
    begin_key = "telegram:update:begin:2437"
    memory = ConversationMemory(updates={begin_key: private_message(update_id=2437, text="/begin")})
    async with await ConversationWorkflowStory.open(
        memory=memory,
        inactivity_timeout_seconds=5,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            await story.start(begin_key)
            await memory.wait_for_messages(2)
            await story.environment.sleep(timedelta(seconds=6))
            await memory.wait_for_messages(3)

        assert (
            memory.messages,
            memory.conversations,
            memory.responses,
        ) == (
            [
                (241_109, "mock conversation started"),
                (241_109, "q1?"),
                (241_109, "your answers were deleted from our system"),
            ],
            {},
            {},
        ), "inactivity timeout failed to clean Redis or send the configured privacy notice"


async def test_restarts_an_active_conversation_without_a_deletion_notice() -> None:
    first_begin_key = "telegram:update:begin:2441"
    second_begin_key = "telegram:update:begin:2447"
    memory = ConversationMemory(
        updates={
            first_begin_key: private_message(update_id=2441, text="/begin"),
            second_begin_key: private_message(update_id=2447, text="/begin"),
        }
    )
    async with await ConversationWorkflowStory.open(
        memory=memory,
        inactivity_timeout_seconds=300,
    ) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start(first_begin_key)
            await memory.wait_for_messages(2)
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=second_begin_key),
            )
            await memory.wait_for_messages(4)

        assert (
            memory.messages,
            tuple(memory.conversations),
        ) == (
            [
                (241_109, "mock conversation started"),
                (241_109, "q1?"),
                (241_109, "mock conversation started"),
                (241_109, "q1?"),
            ],
            (f"{second_begin_key}:conversation",),
        ), "repeated /begin did not silently replace the active conversation snapshot"


async def test_finishes_when_the_conversation_cannot_be_started() -> None:
    transcript = ConversationActivityTranscript(
        start_outcome=ApplicationError("snapshot rejected", non_retryable=True),
        turn_outcomes={},
    )
    async with await FaultConversationWorkflowStory.open(transcript.definitions()) as story:
        handle = await story.start()

        await handle.result()

        assert transcript.events == [("start", "telegram:conversation:fault:2401")], (
            "failed start continued into delivery or conversation processing"
        )


async def test_cleans_private_data_when_initial_delivery_and_cleanup_fail() -> None:
    transcript = ConversationActivityTranscript(
        start_outcome=ConversationStarted(
            response_keys=("telegram:response:initial:2467",),
            privacy_response_key="telegram:response:privacy:2473",
        ),
        turn_outcomes={},
        failed_deliveries={"telegram:response:initial:2467"},
        fail_cleanup=True,
    )
    async with await FaultConversationWorkflowStory.open(transcript.definitions()) as story:
        handle = await story.start()

        await handle.result()

        assert transcript.events == [
            ("start", "telegram:conversation:fault:2401"),
            ("deliver", "telegram:response:initial:2467"),
            ("cleanup", ("telegram:response:initial:2467",)),
            ("cleanup", ("telegram:conversation:fault:2401",)),
            ("deliver", "telegram:response:privacy:2473"),
            ("cleanup", ("telegram:response:privacy:2473",)),
        ], "delivery failure skipped best-effort conversation and privacy cleanup"


async def test_finishes_privately_when_recording_an_answer_fails() -> None:
    update_key = "telegram:update:fault:2503"
    transcript = ConversationActivityTranscript(
        start_outcome=ConversationStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2503",
        ),
        turn_outcomes={update_key: ApplicationError("record rejected", non_retryable=True)},
    )
    async with await FaultConversationWorkflowStory.open(transcript.definitions()) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start()
            await transcript.wait_for("start", 1)
            await handle.signal(
                CONVERSATION_UPDATE_SIGNAL_NAME,
                ConversationUpdateSignal(update_key=update_key),
            )
            await handle.result()

        assert transcript.events == [
            ("start", "telegram:conversation:fault:2401"),
            ("record", update_key),
            (
                "cleanup",
                ("telegram:conversation:fault:2401", update_key),
            ),
            ("deliver", "telegram:response:privacy:2503"),
            ("cleanup", ("telegram:response:privacy:2503",)),
        ], "failed answer recording left the update or conversation snapshot behind"


async def test_ignores_duplicate_input_then_finishes_an_expired_conversation() -> None:
    ignored_key = "telegram:update:ignored:2521"
    expired_key = "telegram:update:expired:2531"
    transcript = ConversationActivityTranscript(
        start_outcome=ConversationStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2539",
        ),
        turn_outcomes={
            ignored_key: ConversationTurn(kind=ConversationTurnKind.IGNORED),
            expired_key: ConversationTurn(kind=ConversationTurnKind.EXPIRED),
        },
        blocked_updates={ignored_key},
    )
    async with await FaultConversationWorkflowStory.open(transcript.definitions()) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start()
            await transcript.wait_for("start", 1)
            await handle.signal(
                CONVERSATION_UPDATE_SIGNAL_NAME,
                ConversationUpdateSignal(update_key=ignored_key),
            )
            await asyncio.wait_for(transcript.record_started.wait(), timeout=7)
            await handle.signal(
                CONVERSATION_UPDATE_SIGNAL_NAME,
                ConversationUpdateSignal(update_key=ignored_key),
            )
            transcript.release_record.set()
            await transcript.wait_for("cleanup", 1)
            await handle.signal(
                CONVERSATION_UPDATE_SIGNAL_NAME,
                ConversationUpdateSignal(update_key=expired_key),
            )
            await handle.result()

        assert [event for event in transcript.events if event[0] == "record"] == [
            ("record", ignored_key),
            ("record", expired_key),
        ], "ignored duplicate advanced the questionnaire or expiration failed to finish it"


async def test_cancellation_cleans_an_update_being_recorded() -> None:
    update_key = "telegram:update:blocked:2551"
    transcript = ConversationActivityTranscript(
        start_outcome=ConversationStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2557",
        ),
        turn_outcomes={update_key: ConversationTurn(kind=ConversationTurnKind.QUESTION)},
        blocked_updates={update_key},
    )
    async with await FaultConversationWorkflowStory.open(transcript.definitions()) as story:
        with story.environment.auto_time_skipping_disabled():
            handle = await story.start()
            await transcript.wait_for("start", 1)
            await handle.signal(
                CONVERSATION_UPDATE_SIGNAL_NAME,
                ConversationUpdateSignal(update_key=update_key),
            )
            await asyncio.wait_for(transcript.record_started.wait(), timeout=7)
            await handle.cancel()
            await transcript.wait_for("cleanup", 1)

        assert (
            "cleanup",
            (
                "telegram:conversation:fault:2401",
                update_key,
                "telegram:response:privacy:2557",
            ),
        ) in transcript.events, "cancellation failed to clean the answer currently being recorded"
