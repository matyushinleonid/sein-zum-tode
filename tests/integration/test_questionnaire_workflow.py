import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import timedelta
from types import TracebackType
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
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
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TELEGRAM_USER_WORKFLOW_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.mortals.activities import (
    CHECK_MORTAL_QUOTA_ACTIVITY_NAME,
    ENSURE_MORTAL_ACTIVITY_NAME,
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
    MortalActivityInput,
    MortalRegistration,
)
from sein_zum_tode.prediction.activities import (
    APPLY_DEATH_PREDICTION_ACTIVITY_NAME,
    GENERATE_DEATH_PREDICTION_ACTIVITY_NAME,
    PREPARE_PREDICTION_FAILURE_ACTIVITY_NAME,
    ApplyDeathPredictionActivity,
    ApplyDeathPredictionInput,
    GenerateDeathPredictionActivity,
    GenerateDeathPredictionInput,
    PreparePredictionFailureActivity,
    PreparePredictionFailureInput,
)
from sein_zum_tode.prediction.config import MockPredictionConfig
from sein_zum_tode.prediction.mock import MockDeathPredictor
from sein_zum_tode.questionnaire.activities import (
    RecordTelegramQuestionnaireAnswerActivity,
    StartTelegramQuestionnaireActivity,
)
from sein_zum_tode.questionnaire.models import (
    QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
    RECORD_QUESTIONNAIRE_ANSWER_ACTIVITY_NAME,
    START_QUESTIONNAIRE_ACTIVITY_NAME,
    TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME,
    QuestionnaireStarted,
    QuestionnaireTurn,
    QuestionnaireTurnKind,
    QuestionnaireUpdateSignal,
    QuestionnaireWorkflowInput,
    RecordQuestionnaireAnswerInput,
    StartQuestionnaireInput,
)
from sein_zum_tode.questionnaire.workflow import TelegramQuestionnaireWorkflow
from tests.support import (
    TEST_TIMEOUT_SECONDS,
    BotContents,
    MortalMemory,
    MortalScheduleMemory,
    QuestionnaireMemory,
    SilentLogger,
    TelegramUpdates,
    mortal,
)

pytestmark = [
    pytest.mark.deep,
    pytest.mark.asyncio(loop_scope="module"),
]


class QuestionnaireActivityTranscript:
    def __init__(
        self,
        *,
        start_outcome: object,
        turn_outcomes: dict[str, object],
        failed_deliveries: set[str] | None = None,
        fail_cleanup: bool = False,
        blocked_updates: set[str] | None = None,
        unavailable_deliveries: set[str] | None = None,
        fail_activation: bool = False,
        fail_prediction_failure_response: bool = False,
        fail_mark_unreachable: bool = False,
    ) -> None:
        self.start_outcome = start_outcome
        self.turn_outcomes = turn_outcomes
        self.failed_deliveries = failed_deliveries or set()
        self.fail_cleanup = fail_cleanup
        self.blocked_updates = blocked_updates or set()
        self.unavailable_deliveries = unavailable_deliveries or set()
        self.fail_activation = fail_activation
        self.fail_prediction_failure_response = fail_prediction_failure_response
        self.fail_mark_unreachable = fail_mark_unreachable
        self.events: list[tuple[object, ...]] = []
        self.changed = asyncio.Event()
        self.record_started = asyncio.Event()
        self.release_record = asyncio.Event()

    def record_event(self, *event: object) -> None:
        self.events.append(event)
        self.changed.set()

    @activity.defn(name=START_QUESTIONNAIRE_ACTIVITY_NAME)
    async def start(self, input: StartQuestionnaireInput) -> QuestionnaireStarted:
        self.record_event("start", input.questionnaire_key)
        if isinstance(self.start_outcome, BaseException):
            raise self.start_outcome
        return cast(QuestionnaireStarted, self.start_outcome)

    @activity.defn(name=RECORD_QUESTIONNAIRE_ANSWER_ACTIVITY_NAME)
    async def record(self, input: RecordQuestionnaireAnswerInput) -> QuestionnaireTurn:
        self.record_event("record", input.update_key)
        if input.update_key in self.blocked_updates:
            self.record_started.set()
            await self.release_record.wait()
        outcome = self.turn_outcomes[input.update_key]
        if isinstance(outcome, BaseException):
            raise outcome
        return cast(QuestionnaireTurn, outcome)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        self.record_event("deliver", input.response_key)
        if input.response_key in self.failed_deliveries:
            raise ApplicationError("delivery rejected", non_retryable=True)
        if input.response_key in self.unavailable_deliveries:
            raise ApplicationError(
                "recipient blocked the bot",
                type="TelegramRecipientUnavailable",
                non_retryable=True,
            )

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        self.record_event("cleanup", input.keys)
        if self.fail_cleanup:
            raise ApplicationError("cleanup rejected", non_retryable=True)

    @activity.defn(name=GENERATE_DEATH_PREDICTION_ACTIVITY_NAME)
    async def generate_prediction(self, input: GenerateDeathPredictionInput) -> None:
        self.record_event("generate_prediction", input.prediction_key)

    @activity.defn(name=APPLY_DEATH_PREDICTION_ACTIVITY_NAME)
    async def apply_prediction(self, input: ApplyDeathPredictionInput) -> None:
        self.record_event("apply_prediction", input.prediction_key)
        if self.fail_activation:
            raise ApplicationError("prediction unavailable", non_retryable=True)

    @activity.defn(name=PREPARE_PREDICTION_FAILURE_ACTIVITY_NAME)
    async def prepare_prediction_failure(
        self,
        input: PreparePredictionFailureInput,
    ) -> None:
        self.record_event("prepare_prediction_failure", input.response_key)
        if self.fail_prediction_failure_response:
            raise ApplicationError("failure response unavailable", non_retryable=True)

    @activity.defn(name=MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME)
    async def mark_mortal_unreachable(self, input: MortalActivityInput) -> None:
        self.record_event("mark_mortal_unreachable", input.mortal_id)
        if self.fail_mark_unreachable:
            raise ApplicationError("reachability update unavailable", non_retryable=True)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.start,
            self.record,
            self.deliver,
            self.cleanup,
            self.generate_prediction,
            self.apply_prediction,
            self.prepare_prediction_failure,
            self.mark_mortal_unreachable,
        ]

    async def wait_for(self, operation: str, count: int) -> None:
        while sum(event[0] == operation for event in self.events) < count:
            self.changed.clear()
            await asyncio.wait_for(
                self.changed.wait(),
                timeout=TEST_TIMEOUT_SECONDS,
            )


class QuestionnaireActivityRouter:
    def __init__(self) -> None:
        self._transcript: QuestionnaireActivityTranscript | None = None

    def use(self, transcript: QuestionnaireActivityTranscript) -> None:
        self._transcript = transcript

    def selected(self) -> QuestionnaireActivityTranscript:
        if self._transcript is None:
            raise RuntimeError("Questionnaire Activity transcript is not selected")
        return self._transcript

    @activity.defn(name=START_QUESTIONNAIRE_ACTIVITY_NAME)
    async def start(self, input: StartQuestionnaireInput) -> QuestionnaireStarted:
        return await self.selected().start(input)

    @activity.defn(name=RECORD_QUESTIONNAIRE_ANSWER_ACTIVITY_NAME)
    async def record(self, input: RecordQuestionnaireAnswerInput) -> QuestionnaireTurn:
        return await self.selected().record(input)

    @activity.defn(name=DELIVER_RESPONSE_ACTIVITY_NAME)
    async def deliver(self, input: DeliverResponseInput) -> None:
        await self.selected().deliver(input)

    @activity.defn(name=CLEANUP_PAYLOADS_ACTIVITY_NAME)
    async def cleanup(self, input: CleanupPayloadsInput) -> None:
        await self.selected().cleanup(input)

    @activity.defn(name=GENERATE_DEATH_PREDICTION_ACTIVITY_NAME)
    async def generate_prediction(self, input: GenerateDeathPredictionInput) -> None:
        await self.selected().generate_prediction(input)

    @activity.defn(name=APPLY_DEATH_PREDICTION_ACTIVITY_NAME)
    async def apply_prediction(self, input: ApplyDeathPredictionInput) -> None:
        await self.selected().apply_prediction(input)

    @activity.defn(name=PREPARE_PREDICTION_FAILURE_ACTIVITY_NAME)
    async def prepare_prediction_failure(
        self,
        input: PreparePredictionFailureInput,
    ) -> None:
        await self.selected().prepare_prediction_failure(input)

    @activity.defn(name=MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME)
    async def mark_mortal_unreachable(self, input: MortalActivityInput) -> None:
        await self.selected().mark_mortal_unreachable(input)

    def definitions(self) -> Sequence[Callable[..., object]]:
        return [
            self.start,
            self.record,
            self.deliver,
            self.cleanup,
            self.generate_prediction,
            self.apply_prediction,
            self.prepare_prediction_failure,
            self.mark_mortal_unreachable,
        ]


class FaultQuestionnaireWorkflowStory:
    def __init__(
        self,
        *,
        environment: WorkflowEnvironment,
        worker: Worker,
        task_queue: str,
        activities: QuestionnaireActivityRouter,
    ) -> None:
        self.environment = environment
        self.worker = worker
        self.task_queue = task_queue
        self.activities = activities
        self.handles: list[WorkflowHandle[TelegramQuestionnaireWorkflow, None]] = []

    @classmethod
    async def open(
        cls,
        *,
        environment: WorkflowEnvironment,
    ) -> FaultQuestionnaireWorkflowStory:
        task_queue = f"fault-questionnaire-{uuid4()}"
        activities = QuestionnaireActivityRouter()
        worker = Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramQuestionnaireWorkflow],
            activities=activities.definitions(),
        )
        await worker.__aenter__()
        return cls(
            environment=environment,
            worker=worker,
            task_queue=task_queue,
            activities=activities,
        )

    def use(self, transcript: QuestionnaireActivityTranscript) -> None:
        self.activities.use(transcript)

    async def close(self) -> None:
        for handle in self.handles:
            await handle.cancel()
        await self.worker.__aexit__(None, None, None)

    async def start(self) -> WorkflowHandle[TelegramQuestionnaireWorkflow, None]:
        handle = await self.environment.client.start_workflow(
            TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME,
            QuestionnaireWorkflowInput(
                questionnaire_key="telegram:questionnaire:fault:2401",
                user_id=240_103,
                chat_id=240_109,
                inactivity_timeout_seconds=300,
                activity_retry_timeout_seconds=7,
            ),
            id=f"fault-questionnaire-{uuid4()}",
            task_queue=self.task_queue,
        )
        self.handles.append(handle)
        return handle


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def fault_questionnaire_story(
    temporal_environment: WorkflowEnvironment,
) -> AsyncIterator[FaultQuestionnaireWorkflowStory]:
    story = await FaultQuestionnaireWorkflowStory.open(
        environment=temporal_environment,
    )
    yield story
    await story.close()


class QuestionnaireWorkflowStory:
    def __init__(
        self,
        *,
        environment: WorkflowEnvironment,
        worker: Worker,
        task_queue: str,
        memory: QuestionnaireMemory,
        inactivity_timeout_seconds: int,
    ) -> None:
        self.environment = environment
        self.worker = worker
        self.task_queue = task_queue
        self.memory = memory
        self.inactivity_timeout_seconds = inactivity_timeout_seconds
        self.handles: list[WorkflowHandle[TelegramUserWorkflow, None]] = []

    @staticmethod
    @activity.defn(name=ENSURE_MORTAL_ACTIVITY_NAME)
    async def ensure_mortal(input: MortalActivityInput) -> MortalRegistration:
        return MortalRegistration(localization_required=False)

    @staticmethod
    @activity.defn(name=CHECK_MORTAL_QUOTA_ACTIVITY_NAME)
    async def has_quota(input: MortalActivityInput) -> bool:
        return True

    @classmethod
    async def open(
        cls,
        *,
        environment: WorkflowEnvironment,
        memory: QuestionnaireMemory,
        inactivity_timeout_seconds: int,
    ) -> QuestionnaireWorkflowStory:
        task_queue = f"deep-questionnaire-{uuid4()}"
        content = BotContents.debug()
        mortals = MortalMemory({241_103: mortal(id=241_103, locale="en")})
        schedules = MortalScheduleMemory()
        inspect = InspectTelegramUpdateActivity(
            update_reader=memory.update_documents,
            logger=SilentLogger(),
        )
        prepare = PrepareTelegramResponseActivities(
            response_store=memory.response_documents,
            ttl_seconds=211,
            content=content,
            mortals=mortals,
            logger=SilentLogger(),
        )
        start = StartTelegramQuestionnaireActivity(
            content=content,
            mortals=mortals,
            questionnaires=memory.questionnaire_repository,
            responses=memory.response_documents,
            questionnaire_ttl_seconds=inactivity_timeout_seconds,
            response_ttl_seconds=211,
            privacy_response_ttl_seconds=inactivity_timeout_seconds + 7,
            logger=SilentLogger(),
        )
        record = RecordTelegramQuestionnaireAnswerActivity(
            updates=memory.update_documents,
            questionnaires=memory.questionnaire_repository,
            responses=memory.response_documents,
            questionnaire_ttl_seconds=inactivity_timeout_seconds,
            response_ttl_seconds=211,
            privacy_response_ttl_seconds=inactivity_timeout_seconds + 7,
            logger=SilentLogger(),
        )
        deliver = DeliverTelegramResponseActivity(
            response_reader=memory.response_documents,
            sender=memory,
            logger=SilentLogger(),
        )
        cleanup = CleanupTelegramPayloadsActivity(
            cleaner=memory,
            logger=SilentLogger(),
        )
        generate_prediction = GenerateDeathPredictionActivity(
            predictor=MockDeathPredictor(
                config=MockPredictionConfig(days_left=26837),
                content=content,
            ),
            predictions=memory.prediction_repository,
            questionnaires=memory.questionnaire_repository,
            mortals=mortals,
            ttl_seconds=inactivity_timeout_seconds,
            logger=SilentLogger(),
        )
        apply_prediction = ApplyDeathPredictionActivity(
            predictions=memory.prediction_repository,
            mortals=mortals,
            schedules=schedules,
            responses=memory.response_documents,
            response_ttl_seconds=211,
            logger=SilentLogger(),
        )
        prepare_prediction_failure = PreparePredictionFailureActivity(
            mortals=mortals,
            responses=memory.response_documents,
            content=content,
            response_ttl_seconds=211,
        )
        worker = Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[TelegramUserWorkflow, TelegramQuestionnaireWorkflow],
            activities=[
                inspect.inspect,
                prepare.prepare_help,
                prepare.prepare_unsupported,
                prepare.prepare_group_unsupported,
                start.start,
                record.record,
                deliver.deliver,
                cleanup.cleanup,
                cls.ensure_mortal,
                cls.has_quota,
                generate_prediction.generate,
                apply_prediction.apply,
                prepare_prediction_failure.prepare,
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

    async def __aenter__(self) -> QuestionnaireWorkflowStory:
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

    async def start(
        self,
        begin_key: str,
    ) -> WorkflowHandle[TelegramUserWorkflow, None]:
        handle = await self.environment.client.start_workflow(
            TELEGRAM_USER_WORKFLOW_NAME,
            UserWorkflowInput(
                user_id=241_103,
                activity_retry_timeout_seconds=7,
                questionnaire_ttl_seconds=self.inactivity_timeout_seconds,
            ),
            id=f"deep-questionnaire-user-{uuid4()}",
            task_queue=self.task_queue,
            start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
            start_signal_args=[TelegramUpdateSignal(redis_key=begin_key)],
        )
        self.handles.append(handle)
        return handle


def private_message(*, update_id: int, text: str) -> Update:
    return TelegramUpdates.message(
        update_id=update_id,
        user_id=241_103,
        chat_id=241_109,
        text=text,
        chat_type="private",
    )


async def test_runs_the_complete_private_questionnaire_without_persisting_answers(
    temporal_environment: WorkflowEnvironment,
) -> None:
    begin_key = "telegram:update:begin:2411"
    first_answer_key = "telegram:update:answer:2417"
    second_answer_key = "telegram:update:answer:2423"
    text_key = "telegram:update:text:2437"
    first_secret = "Sensitive first answer 2417"
    second_secret = "Sensitive second answer 2423"
    memory = QuestionnaireMemory(
        updates={
            begin_key: private_message(update_id=2411, text="/begin"),
            first_answer_key: private_message(update_id=2417, text=first_secret),
            second_answer_key: private_message(update_id=2423, text=second_secret),
            text_key: private_message(update_id=2437, text="Text after completion"),
        }
    )
    async with await QuestionnaireWorkflowStory.open(
        environment=temporal_environment,
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
            await memory.wait_for_messages(6)
            await memory.wait_until_absent(f"{begin_key}:questionnaire:privacy")
            await handle.signal(
                TELEGRAM_UPDATE_SIGNAL_NAME,
                TelegramUpdateSignal(redis_key=text_key),
            )
            await memory.wait_for_messages(7)
            await memory.wait_until_absent(f"{text_key}:response")
            child_id = f"{handle.id}:questionnaire:{begin_key}"
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
            (241_109, "mock questionnaire started"),
            (241_109, "q1?"),
            (241_109, "q2?"),
            (241_109, "thanks for your answers!"),
            (
                241_109,
                f"Mock prediction: q1-{first_secret}, q2-{second_secret}",
            ),
            (241_109, "your answers were deleted from our system"),
            (241_109, "Use /help to learn how to use the bot"),
        ], "parent and child Workflows did not execute the configured questionnaire in order"
        assert (
            memory.questionnaires,
            memory.responses,
            memory.predictions,
            first_answer_key in memory.updates,
            second_answer_key in memory.updates,
            text_key in memory.updates,
            first_secret not in histories,
            second_secret not in histories,
        ) == (
            {},
            {},
            {},
            False,
            False,
            False,
            True,
            True,
        ), "completion retained private Redis data or persisted answers in Temporal history"


async def test_deletes_an_inactive_questionnaire_and_notifies_the_user(
    temporal_environment: WorkflowEnvironment,
) -> None:
    begin_key = "telegram:update:begin:2437"
    memory = QuestionnaireMemory(
        updates={begin_key: private_message(update_id=2437, text="/begin")}
    )
    async with await QuestionnaireWorkflowStory.open(
        environment=temporal_environment,
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
            memory.questionnaires,
            memory.responses,
        ) == (
            [
                (241_109, "mock questionnaire started"),
                (241_109, "q1?"),
                (241_109, "your answers were deleted from our system"),
            ],
            {},
            {},
        ), "inactivity timeout failed to clean Redis or send the configured privacy notice"


async def test_restarts_an_active_questionnaire_without_a_deletion_notice(
    temporal_environment: WorkflowEnvironment,
) -> None:
    first_begin_key = "telegram:update:begin:2441"
    second_begin_key = "telegram:update:begin:2447"
    memory = QuestionnaireMemory(
        updates={
            first_begin_key: private_message(update_id=2441, text="/begin"),
            second_begin_key: private_message(update_id=2447, text="/begin"),
        }
    )
    async with await QuestionnaireWorkflowStory.open(
        environment=temporal_environment,
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
            tuple(memory.questionnaires),
        ) == (
            [
                (241_109, "mock questionnaire started"),
                (241_109, "q1?"),
                (241_109, "mock questionnaire started"),
                (241_109, "q1?"),
            ],
            (f"{second_begin_key}:questionnaire",),
        ), "repeated /begin did not silently replace the active questionnaire snapshot"


async def test_finishes_when_the_questionnaire_cannot_be_started(
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    transcript = QuestionnaireActivityTranscript(
        start_outcome=ApplicationError("snapshot rejected", non_retryable=True),
        turn_outcomes={},
    )
    fault_questionnaire_story.use(transcript)
    handle = await fault_questionnaire_story.start()

    await handle.result()

    assert transcript.events == [("start", "telegram:questionnaire:fault:2401")], (
        "failed start continued into delivery or questionnaire processing"
    )


async def test_cleans_private_data_when_initial_delivery_and_cleanup_fail(
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    transcript = QuestionnaireActivityTranscript(
        start_outcome=QuestionnaireStarted(
            response_keys=("telegram:response:initial:2467",),
            privacy_response_key="telegram:response:privacy:2473",
        ),
        turn_outcomes={},
        failed_deliveries={"telegram:response:initial:2467"},
        fail_cleanup=True,
    )
    fault_questionnaire_story.use(transcript)
    handle = await fault_questionnaire_story.start()

    await handle.result()

    assert transcript.events == [
        ("start", "telegram:questionnaire:fault:2401"),
        ("deliver", "telegram:response:initial:2467"),
        ("cleanup", ("telegram:response:initial:2467",)),
        ("deliver", "telegram:response:privacy:2473"),
        (
            "cleanup",
            (
                "telegram:questionnaire:fault:2401",
                "telegram:response:privacy:2473",
            ),
        ),
    ], "delivery failure skipped best-effort questionnaire and privacy cleanup"


async def test_finishes_privately_when_recording_an_answer_fails(
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    update_key = "telegram:update:fault:2503"
    transcript = QuestionnaireActivityTranscript(
        start_outcome=QuestionnaireStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2503",
        ),
        turn_outcomes={update_key: ApplicationError("record rejected", non_retryable=True)},
    )
    fault_questionnaire_story.use(transcript)
    with fault_questionnaire_story.environment.auto_time_skipping_disabled():
        handle = await fault_questionnaire_story.start()
        await transcript.wait_for("start", 1)
        await handle.signal(
            QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
            QuestionnaireUpdateSignal(update_key=update_key),
        )
        await handle.result()

    assert transcript.events == [
        ("start", "telegram:questionnaire:fault:2401"),
        ("record", update_key),
        ("deliver", "telegram:response:privacy:2503"),
        (
            "cleanup",
            (
                "telegram:questionnaire:fault:2401",
                update_key,
                "telegram:response:privacy:2503",
            ),
        ),
    ], "failed answer recording left the update or questionnaire snapshot behind"


async def test_ignores_duplicate_input_then_finishes_an_expired_questionnaire(
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    ignored_key = "telegram:update:ignored:2521"
    expired_key = "telegram:update:expired:2531"
    transcript = QuestionnaireActivityTranscript(
        start_outcome=QuestionnaireStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2539",
        ),
        turn_outcomes={
            ignored_key: QuestionnaireTurn(kind=QuestionnaireTurnKind.IGNORED),
            expired_key: QuestionnaireTurn(kind=QuestionnaireTurnKind.EXPIRED),
        },
        blocked_updates={ignored_key},
    )
    fault_questionnaire_story.use(transcript)
    with fault_questionnaire_story.environment.auto_time_skipping_disabled():
        handle = await fault_questionnaire_story.start()
        await transcript.wait_for("start", 1)
        await handle.signal(
            QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
            QuestionnaireUpdateSignal(update_key=ignored_key),
        )
        await asyncio.wait_for(
            transcript.record_started.wait(),
            timeout=TEST_TIMEOUT_SECONDS,
        )
        await handle.signal(
            QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
            QuestionnaireUpdateSignal(update_key=ignored_key),
        )
        transcript.release_record.set()
        await transcript.wait_for("cleanup", 1)
        await handle.signal(
            QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
            QuestionnaireUpdateSignal(update_key=expired_key),
        )
        await handle.result()

    assert [event for event in transcript.events if event[0] == "record"] == [
        ("record", ignored_key),
        ("record", expired_key),
    ], "ignored duplicate advanced the questionnaire or expiration failed to finish it"


async def test_cancellation_cleans_an_update_being_recorded(
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    update_key = "telegram:update:blocked:2551"
    transcript = QuestionnaireActivityTranscript(
        start_outcome=QuestionnaireStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2557",
        ),
        turn_outcomes={update_key: QuestionnaireTurn(kind=QuestionnaireTurnKind.QUESTION)},
        blocked_updates={update_key},
    )
    fault_questionnaire_story.use(transcript)
    with fault_questionnaire_story.environment.auto_time_skipping_disabled():
        handle = await fault_questionnaire_story.start()
        await transcript.wait_for("start", 1)
        await handle.signal(
            QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
            QuestionnaireUpdateSignal(update_key=update_key),
        )
        await asyncio.wait_for(
            transcript.record_started.wait(),
            timeout=TEST_TIMEOUT_SECONDS,
        )
        await handle.cancel()
        await transcript.wait_for("cleanup", 1)

    assert (
        "cleanup",
        (
            "telegram:questionnaire:fault:2401",
            update_key,
            "telegram:response:privacy:2557",
        ),
    ) in transcript.events, "cancellation failed to clean the answer currently being recorded"


async def test_activation_failure_does_not_restore_private_redis_data(
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    update_key = "telegram:update:completed:2579"
    response_key = "telegram:response:completed:2591"
    transcript = QuestionnaireActivityTranscript(
        start_outcome=QuestionnaireStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2593",
        ),
        turn_outcomes={
            update_key: QuestionnaireTurn(
                kind=QuestionnaireTurnKind.COMPLETED,
                response_keys=(response_key,),
            )
        },
        fail_activation=True,
    )
    fault_questionnaire_story.use(transcript)
    with fault_questionnaire_story.environment.auto_time_skipping_disabled():
        handle = await fault_questionnaire_story.start()
        await transcript.wait_for("start", 1)
        await handle.signal(
            QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
            QuestionnaireUpdateSignal(update_key=update_key),
        )
        await handle.result()

    assert [event[0] for event in transcript.events] == [
        "start",
        "record",
        "deliver",
        "generate_prediction",
        "apply_prediction",
        "prepare_prediction_failure",
        "deliver",
        "deliver",
        "cleanup",
    ], "prediction failure changed the private-data completion sequence"


async def test_prediction_and_fallback_failure_still_deliver_privacy_notice(
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    update_key = "telegram:update:prediction-double-failure:2597"
    response_key = "telegram:response:prediction-double-failure:2599"
    transcript = QuestionnaireActivityTranscript(
        start_outcome=QuestionnaireStarted(
            response_keys=(),
            privacy_response_key="telegram:response:privacy:2603",
        ),
        turn_outcomes={
            update_key: QuestionnaireTurn(
                kind=QuestionnaireTurnKind.COMPLETED,
                response_keys=(response_key,),
            )
        },
        fail_activation=True,
        fail_prediction_failure_response=True,
    )
    fault_questionnaire_story.use(transcript)
    with fault_questionnaire_story.environment.auto_time_skipping_disabled():
        handle = await fault_questionnaire_story.start()
        await transcript.wait_for("start", 1)
        await handle.signal(
            QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
            QuestionnaireUpdateSignal(update_key=update_key),
        )
        await handle.result()

    assert [event[0] for event in transcript.events][-3:] == [
        "deliver",
        "deliver",
        "cleanup",
    ], "failed prediction fallback skipped response attempt, privacy notice, or cleanup"


@pytest.mark.parametrize("fail_mark_unreachable", [False, True])
async def test_forbidden_questionnaire_delivery_marks_the_mortal_unreachable(
    fail_mark_unreachable: bool,
    fault_questionnaire_story: FaultQuestionnaireWorkflowStory,
) -> None:
    response_key = "telegram:response:forbidden:2609"
    transcript = QuestionnaireActivityTranscript(
        start_outcome=QuestionnaireStarted(
            response_keys=(response_key,),
            privacy_response_key="telegram:response:privacy:2617",
        ),
        turn_outcomes={},
        unavailable_deliveries={response_key},
        fail_mark_unreachable=fail_mark_unreachable,
    )
    fault_questionnaire_story.use(transcript)
    handle = await fault_questionnaire_story.start()
    await handle.result()

    assert [event[0] for event in transcript.events[:4]] == [
        "start",
        "deliver",
        "mark_mortal_unreachable",
        "cleanup",
    ], "forbidden questionnaire delivery did not update Mortal reachability"
