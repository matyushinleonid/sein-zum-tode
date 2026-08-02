from datetime import UTC, date, datetime

import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.infrastructure.clock import SystemClock
from sein_zum_tode.prediction.activities import (
    ApplyDeathPredictionActivity,
    ApplyDeathPredictionInput,
    GenerateDeathPredictionActivity,
    GenerateDeathPredictionInput,
    PreparePredictionFailureActivity,
    PreparePredictionFailureInput,
)
from sein_zum_tode.prediction.models import (
    DeathPrediction,
    DeathPredictionRequest,
    StoredDeathPrediction,
)
from sein_zum_tode.questionnaire.models import QuestionnaireState
from tests.support import (
    BotContents,
    MortalMemory,
    MortalScheduleMemory,
    QuestionnaireMemory,
    SilentLogger,
    mortal,
)

pytestmark = pytest.mark.fast


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 30, 5, 0, tzinfo=UTC)


class PredictorDouble:
    def __init__(
        self,
        *,
        consumes_quota: bool,
        prediction_possible: bool = True,
    ) -> None:
        self._consumes_quota = consumes_quota
        self._prediction_possible = prediction_possible
        self.events: list[DeathPredictionRequest] = []

    @property
    def provider_name(self) -> str:
        return "yandex" if self._consumes_quota else "mock"

    @property
    def consumes_quota(self) -> bool:
        return self._consumes_quota

    async def predict(self, request: DeathPredictionRequest) -> DeathPrediction:
        self.events.append(request)
        return DeathPrediction(
            prediction_possible=self._prediction_possible,
            days_left=17 if self._prediction_possible else None,
            message=(
                "Typed prediction"
                if self._prediction_possible
                else "Please provide meaningful answers."
            ),
        )

    async def close(self) -> None:
        return None


class FailingPredictor:
    provider_name = "yandex"
    consumes_quota = True

    async def predict(self, request: DeathPredictionRequest) -> DeathPrediction:
        raise RuntimeError("prediction provider failed 3719")

    async def close(self) -> None:
        return None


def completed_state() -> QuestionnaireState:
    content = BotContents.debug()
    state = QuestionnaireState.begin(
        content=content,
        localized=content.default(),
        locale="en",
        user_id=372_013,
        chat_id=372_017,
    )
    state = state.apply_answer(update_key="answer:1", text="Alpha").state
    return state.apply_answer(update_key="answer:2", text="Beta").state


async def test_propagates_a_completion_failure_for_temporal_retry() -> None:
    key = "questionnaire:3719"
    state = completed_state()
    subject = GenerateDeathPredictionActivity(
        predictor=FailingPredictor(),
        predictions=QuestionnaireMemory().prediction_repository,
        questionnaires=QuestionnaireMemory(questionnaires={key: state}).questionnaire_repository,
        mortals=MortalMemory({state.user_id: mortal(id=state.user_id)}),
        ttl_seconds=3727,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    with pytest.raises(RuntimeError, match="prediction provider failed"):
        await subject.generate(
            GenerateDeathPredictionInput(
                questionnaire_key=key,
                prediction_key=f"{key}:prediction",
                user_id=state.user_id,
            )
        )


@pytest.mark.parametrize(
    ("consumes_quota", "remaining"),
    [
        (False, 15),
        (True, 14),
    ],
)
async def test_generates_once_and_replays_quota_consumption_idempotently(
    consumes_quota: bool,
    remaining: int,
) -> None:
    key = "questionnaire:3721"
    prediction_key = f"{key}:prediction"
    memory = QuestionnaireMemory(questionnaires={key: completed_state()})
    mortals = MortalMemory({372_013: mortal(id=372_013)})
    predictor = PredictorDouble(consumes_quota=consumes_quota)
    subject = GenerateDeathPredictionActivity(
        predictor=predictor,
        predictions=memory.prediction_repository,
        questionnaires=memory.questionnaire_repository,
        mortals=mortals,
        ttl_seconds=3733,
        clock=FixedClock(),
        logger=SilentLogger(),
    )
    input = GenerateDeathPredictionInput(
        questionnaire_key=key,
        prediction_key=prediction_key,
        user_id=372_013,
    )

    await subject.generate(input)
    await subject.generate(input)

    assert (
        len(predictor.events),
        memory.predictions[prediction_key].prediction,
        memory.predictions[prediction_key].current_date,
        mortals.mortals[372_013].llm_requests_remaining,
    ) == (
        1,
        DeathPrediction(
            prediction_possible=True,
            days_left=17,
            message="Typed prediction",
        ),
        date(2026, 7, 30),
        remaining,
    ), "Activity retry repeated Yandex generation or double-decremented quota"


async def test_consumes_quota_for_a_successful_model_rejection() -> None:
    key = "questionnaire:3727"
    prediction_key = f"{key}:prediction"
    state = completed_state()
    memory = QuestionnaireMemory(questionnaires={key: state})
    mortals = MortalMemory({state.user_id: mortal(id=state.user_id)})
    subject = GenerateDeathPredictionActivity(
        predictor=PredictorDouble(
            consumes_quota=True,
            prediction_possible=False,
        ),
        predictions=memory.prediction_repository,
        questionnaires=memory.questionnaire_repository,
        mortals=mortals,
        ttl_seconds=3739,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    await subject.generate(
        GenerateDeathPredictionInput(
            questionnaire_key=key,
            prediction_key=prediction_key,
            user_id=state.user_id,
        )
    )

    assert (
        memory.predictions[prediction_key].prediction.prediction_possible,
        mortals.mortals[state.user_id].llm_requests_remaining,
    ) == (
        False,
        14,
    ), "a valid structured rejection was treated as a failed, free API call"


@pytest.mark.parametrize(
    ("questionnaire_exists", "mortal_exists"),
    [(False, True), (True, False)],
)
async def test_rejects_expired_prediction_input(
    questionnaire_exists: bool,
    mortal_exists: bool,
) -> None:
    state = completed_state()
    memory = QuestionnaireMemory(
        questionnaires={"questionnaire:3739": state} if questionnaire_exists else {}
    )
    mortals = MortalMemory({state.user_id: mortal(id=state.user_id)} if mortal_exists else {})
    subject = GenerateDeathPredictionActivity(
        predictor=PredictorDouble(consumes_quota=True),
        predictions=memory.prediction_repository,
        questionnaires=memory.questionnaire_repository,
        mortals=mortals,
        ttl_seconds=3749,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.generate(
            GenerateDeathPredictionInput(
                questionnaire_key="questionnaire:3739",
                prediction_key="prediction:3739",
                user_id=state.user_id,
            )
        )


async def test_applies_death_date_schedule_and_response() -> None:
    user_id = 376_039
    memory = QuestionnaireMemory()
    stored = StoredDeathPrediction(
        request_id="request-3761",
        provider="yandex",
        consumes_quota=True,
        current_date=date(2026, 7, 30),
        prediction=DeathPrediction(
            prediction_possible=True,
            days_left=17,
            message="Typed prediction",
        ),
    )
    memory.predictions["prediction:3761"] = stored
    mortals = MortalMemory({user_id: mortal(id=user_id)})
    schedules = MortalScheduleMemory()
    subject = ApplyDeathPredictionActivity(
        predictions=memory.prediction_repository,
        mortals=mortals,
        schedules=schedules,
        responses=memory.response_documents,
        response_ttl_seconds=3767,
        logger=SilentLogger(),
    )

    await subject.apply(
        ApplyDeathPredictionInput(
            prediction_key="prediction:3761",
            response_key="prediction:3761:response",
            user_id=user_id,
            chat_id=376_049,
        )
    )

    assert (
        mortals.mortals[user_id].death_date,
        schedules.events,
        memory.responses["prediction:3761:response"].text,
    ) == (
        date(2026, 8, 16),
        [("ensure", mortals.mortals[user_id])],
        "Typed prediction",
    ), "prediction application lost the calculated date, Schedule, or response"


async def test_returns_rejection_without_changing_death_date_or_schedule() -> None:
    user_id = 376_087
    memory = QuestionnaireMemory()
    memory.predictions["prediction:3769"] = StoredDeathPrediction(
        request_id="request-3769",
        provider="openai",
        consumes_quota=True,
        current_date=date(2026, 7, 30),
        prediction=DeathPrediction(
            prediction_possible=False,
            days_left=None,
            message="Please provide meaningful answers.",
        ),
    )
    original = mortal(id=user_id, death_date=date(2091, 11, 13))
    mortals = MortalMemory({user_id: original})
    schedules = MortalScheduleMemory()
    subject = ApplyDeathPredictionActivity(
        predictions=memory.prediction_repository,
        mortals=mortals,
        schedules=schedules,
        responses=memory.response_documents,
        response_ttl_seconds=3779,
        logger=SilentLogger(),
    )

    await subject.apply(
        ApplyDeathPredictionInput(
            prediction_key="prediction:3769",
            response_key="prediction:3769:response",
            user_id=user_id,
            chat_id=376_091,
        )
    )

    assert (
        mortals.mortals[user_id],
        schedules.events,
        memory.responses["prediction:3769:response"].text,
    ) == (
        original,
        [],
        "Please provide meaningful answers.",
    ), "rejected prediction overwrote the prior date, Schedule, or explanatory response"


async def test_rejects_an_expired_stored_prediction() -> None:
    memory = QuestionnaireMemory()
    responses = QuestionnaireMemory()
    subject = ApplyDeathPredictionActivity(
        predictions=memory.prediction_repository,
        mortals=MortalMemory(),
        schedules=MortalScheduleMemory(),
        responses=responses.response_documents,
        response_ttl_seconds=3779,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.apply(
            ApplyDeathPredictionInput(
                prediction_key="prediction:expired",
                response_key="prediction:expired:response",
                user_id=377_983,
                chat_id=377_987,
            )
        )


async def test_prepares_a_localized_failure_response() -> None:
    user_id = 379_007
    responses = QuestionnaireMemory()
    subject = PreparePredictionFailureActivity(
        mortals=MortalMemory({user_id: mortal(id=user_id, locale="en")}),
        responses=responses.response_documents,
        content=BotContents.debug(),
        response_ttl_seconds=3793,
    )

    await subject.prepare(
        PreparePredictionFailureInput(
            response_key="prediction:failure:3797",
            user_id=user_id,
            chat_id=379_009,
        )
    )

    assert responses.responses["prediction:failure:3797"].text == "Prediction failed"


def test_prediction_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().utcoffset() is not None
