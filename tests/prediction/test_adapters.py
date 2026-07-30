from datetime import date
from typing import cast

import pytest
from pydantic import BaseModel

from sein_zum_tode.prediction.config import MockPredictionConfig
from sein_zum_tode.prediction.mock import MockDeathPredictor
from sein_zum_tode.prediction.models import (
    DeathPrediction,
    DeathPredictionRequest,
    PredictionAnswer,
)
from sein_zum_tode.prediction.ports import StructuredCompletionClient
from sein_zum_tode.prediction.yandex import YandexDeathPredictor
from tests.support import BotContents

pytestmark = pytest.mark.fast


def request() -> DeathPredictionRequest:
    return DeathPredictionRequest(
        current_date=date(2026, 7, 30),
        locale="en",
        answers=(
            PredictionAnswer(
                question_id="q1",
                question="First?",
                answer="Alpha",
            ),
        ),
    )


class StructuredClientDouble(StructuredCompletionClient):
    def __init__(self, response: DeathPrediction) -> None:
        self.response = response
        self.events: list[tuple[object, ...]] = []

    async def complete[ResponseT: BaseModel](
        self,
        *,
        user_prompt: str,
        response_format: type[ResponseT],
    ) -> ResponseT:
        self.events.append((user_prompt, response_format))
        return response_format.model_validate(self.response.model_dump())


async def test_mock_prediction_includes_local_answers_without_consuming_quota() -> None:
    predictor = MockDeathPredictor(
        config=MockPredictionConfig(days_left=3623),
        content=BotContents.debug(),
    )

    actual = await predictor.predict(request())

    assert (
        predictor.provider_name,
        predictor.consumes_quota,
        actual,
    ) == (
        "mock",
        False,
        DeathPrediction(
            days_left=3623,
            message="Mock prediction: q1-Alpha",
        ),
    )


async def test_yandex_adapter_requests_the_enforced_prediction_schema() -> None:
    expected = DeathPrediction(days_left=3631, message="Structured prediction")
    client = StructuredClientDouble(expected)
    predictor = YandexDeathPredictor(client=client)

    actual = await predictor.predict(request())

    assert (
        predictor.provider_name,
        predictor.consumes_quota,
        actual,
        client.events[0][1],
        "Current date: 2026-07-30" in cast(str, client.events[0][0]),
    ) == (
        "yandex",
        True,
        expected,
        DeathPrediction,
        True,
    ), "Yandex adapter did not enforce DeathPrediction as structured response_format"
