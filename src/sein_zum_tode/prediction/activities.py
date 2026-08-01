import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.ports import MortalSchedule
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.documents import DocumentStore, DocumentWriter
from sein_zum_tode.prediction.models import DeathPredictionRequest, StoredDeathPrediction
from sein_zum_tode.prediction.ports import DeathPredictor
from sein_zum_tode.questionnaire.models import QuestionnaireState

GENERATE_DEATH_PREDICTION_ACTIVITY_NAME = "generate_death_prediction"
APPLY_DEATH_PREDICTION_ACTIVITY_NAME = "apply_death_prediction"
PREPARE_PREDICTION_FAILURE_ACTIVITY_NAME = "prepare_prediction_failure"


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GenerateDeathPredictionInput:
    questionnaire_key: str
    prediction_key: str
    user_id: int


@dataclass(frozen=True, slots=True)
class ApplyDeathPredictionInput:
    prediction_key: str
    response_key: str
    user_id: int
    chat_id: int


@dataclass(frozen=True, slots=True)
class PreparePredictionFailureInput:
    response_key: str
    user_id: int
    chat_id: int


class GenerateDeathPredictionActivity:
    def __init__(
        self,
        *,
        predictor: DeathPredictor,
        predictions: DocumentStore[StoredDeathPrediction],
        questionnaires: DocumentStore[QuestionnaireState],
        mortals: MortalRepository,
        ttl_seconds: int,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._predictor = predictor
        self._predictions = predictions
        self._questionnaires = questionnaires
        self._mortals = mortals
        self._ttl_seconds = ttl_seconds
        self._clock = clock or SystemClock()
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=GENERATE_DEATH_PREDICTION_ACTIVITY_NAME)
    async def generate(self, input: GenerateDeathPredictionInput) -> None:
        stored = await self._predictions.load(input.prediction_key)
        if stored is None:
            state = await self._questionnaires.load(input.questionnaire_key)
            mortal = await self._mortals.get(input.user_id)
            if state is None or mortal is None:
                raise ApplicationError(
                    "Prediction input expired",
                    type="PredictionInputNotFound",
                    non_retryable=True,
                )
            request = DeathPredictionRequest(
                current_date=mortal.local_date(self._clock.now()),
                locale=state.locale,
                answers=state.prediction_answers(),
            )
            prediction = await self._predictor.predict(request)
            stored = StoredDeathPrediction(
                request_id=sha256(input.prediction_key.encode()).hexdigest(),
                provider=self._predictor.provider_name,
                consumes_quota=self._predictor.consumes_quota,
                current_date=request.current_date,
                prediction=prediction,
            )
            await self._predictions.store(
                input.prediction_key,
                stored,
                self._ttl_seconds,
            )
        if stored.consumes_quota:
            await self._mortals.consume_llm_request(input.user_id, stored.request_id)
        self._logger.info(
            "Death prediction generated",
            extra=LogContext(component="worker", user_id=input.user_id).event(
                "death_prediction_generated",
                provider=stored.provider,
            ),
        )


class ApplyDeathPredictionActivity:
    def __init__(
        self,
        *,
        predictions: DocumentStore[StoredDeathPrediction],
        mortals: MortalRepository,
        schedules: MortalSchedule,
        responses: DocumentWriter[TelegramResponse],
        response_ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._predictions = predictions
        self._mortals = mortals
        self._schedules = schedules
        self._responses = responses
        self._response_ttl_seconds = response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=APPLY_DEATH_PREDICTION_ACTIVITY_NAME)
    async def apply(self, input: ApplyDeathPredictionInput) -> None:
        stored = await self._predictions.load(input.prediction_key)
        if stored is None:
            raise ApplicationError(
                "Death prediction expired",
                type="DeathPredictionNotFound",
                non_retryable=True,
            )
        death_date = stored.death_date()
        if death_date is not None:
            mortal = await self._mortals.set_death_date(input.user_id, death_date)
            await self._schedules.ensure(mortal)
        await self._responses.store(
            input.response_key,
            TelegramResponse(chat_id=input.chat_id, text=stored.prediction.message),
            self._response_ttl_seconds,
        )
        self._logger.info(
            "Death prediction applied",
            extra=LogContext(component="worker", user_id=input.user_id).event(
                "death_prediction_applied",
                provider=stored.provider,
                prediction_possible=stored.prediction.prediction_possible,
                death_date=death_date.isoformat() if death_date is not None else None,
            ),
        )


class PreparePredictionFailureActivity:
    def __init__(
        self,
        *,
        mortals: MortalRepository,
        responses: DocumentWriter[TelegramResponse],
        content: BotContent,
        response_ttl_seconds: int,
    ) -> None:
        self._mortals = mortals
        self._responses = responses
        self._content = content
        self._response_ttl_seconds = response_ttl_seconds

    @activity.defn(name=PREPARE_PREDICTION_FAILURE_ACTIVITY_NAME)
    async def prepare(self, input: PreparePredictionFailureInput) -> None:
        mortal = await self._mortals.get(input.user_id)
        locale = (
            mortal.locale
            if mortal is not None and mortal.locale is not None
            else self._content.default_locale
        )
        await self._responses.store(
            input.response_key,
            TelegramResponse(
                chat_id=input.chat_id,
                text=self._content.localized(locale).prediction.failed,
            ),
            self._response_ttl_seconds,
        )
