from datetime import date
from typing import cast

import pytest

from sein_zum_tode.prediction.config import MockPredictionConfig
from sein_zum_tode.prediction.llm import LLMDeathPredictor
from sein_zum_tode.prediction.mock import MockDeathPredictor
from sein_zum_tode.prediction.models import (
    DeathPrediction,
    DeathPredictionRequest,
    PredictionAnswer,
)
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


class CompletionClientDouble:
    def __init__(
        self,
        *,
        response: DeathPrediction,
        provider_name: str,
        consumes_quota: bool,
    ) -> None:
        self.response = response
        self.provider_name = provider_name
        self.consumes_quota = consumes_quota
        self.events: list[tuple[object, ...]] = []

    async def complete(self, *, user_prompt: str) -> DeathPrediction:
        self.events.append((user_prompt,))
        return self.response


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


async def test_llm_adapter_delegates_prompt_response_and_provider_metadata() -> None:
    expected = DeathPrediction(days_left=3631, message="Structured prediction")
    client = CompletionClientDouble(
        response=expected,
        provider_name="structured-nebula",
        consumes_quota=True,
    )
    predictor = LLMDeathPredictor(client=client)

    actual = await predictor.predict(request())

    assert (
        predictor.provider_name,
        predictor.consumes_quota,
        actual,
        "Current date: 2026-07-30" in cast(str, client.events[0][0]),
    ) == (
        "structured-nebula",
        True,
        expected,
        True,
    ), "LLM predictor did not delegate the prompt or client metadata"
