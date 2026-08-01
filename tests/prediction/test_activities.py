from datetime import UTC, date, datetime

import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.prediction.activities import (
    ApplyDeathPredictionActivity,
    ApplyDeathPredictionInput,
    GenerateDeathPredictionActivity,
    GenerateDeathPredictionInput,
    PreparePredictionFailureActivity,
    PreparePredictionFailureInput,
    SystemClock,
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
)

pytestmark = pytest.mark.fast


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 30, 5, 0, tzinfo=UTC)


class PredictorDouble:
    def __init__(self, *, consumes_quota: bool) -> None:
        self._consumes_quota = consumes_quota
        self.events: list[DeathPredictionRequest] = []

    @property
    def provider_name(self) -> str:
        return "yandex" if self._consumes_quota else "mock"

    @property
    def consumes_quota(self) -> bool:
        return self._consumes_quota

    async def predict(self, request: DeathPredictionRequest) -> DeathPrediction:
        self.events.append(request)
        return DeathPrediction(days_left=17, message="Typed prediction")


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


@pytest.mark.parametrize(
    ("consumes_quota", "remaining"),
    [
        (False, 50),
        (True, 49),
    ],
)
async def test_generates_once_and_replays_quota_consumption_idempotently(
    consumes_quota: bool,
    remaining: int,
) -> None:
    key = "questionnaire:3721"
    prediction_key = f"{key}:prediction"
    memory = QuestionnaireMemory(questionnaires={key: completed_state()})
    mortals = MortalMemory({372_013: Mortal(id=372_013)})
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
        DeathPrediction(days_left=17, message="Typed prediction"),
        date(2026, 7, 30),
        remaining,
    ), "Activity retry repeated Yandex generation or double-decremented quota"


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
    mortals = MortalMemory({state.user_id: Mortal(id=state.user_id)} if mortal_exists else {})
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
        prediction=DeathPrediction(days_left=17, message="Typed prediction"),
    )
    memory.predictions["prediction:3761"] = stored
    mortals = MortalMemory({user_id: Mortal(id=user_id)})
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
        mortals=MortalMemory({user_id: Mortal(id=user_id, locale="en")}),
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
