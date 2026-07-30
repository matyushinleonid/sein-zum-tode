from datetime import date

import pytest

from sein_zum_tode.prediction.models import (
    DeathPrediction,
    DeathPredictionRequest,
    PredictionAnswer,
    StoredDeathPrediction,
)

pytestmark = pytest.mark.fast


def test_builds_a_dated_localized_questionnaire_prompt() -> None:
    request = DeathPredictionRequest(
        current_date=date(2026, 7, 30),
        locale="en",
        answers=(
            PredictionAnswer(
                question_id="q1",
                question="First?",
                answer="Alpha",
            ),
            PredictionAnswer(
                question_id="q2",
                question="Second?",
                answer="Beta",
            ),
        ),
    )

    assert (
        "Current date: 2026-07-30" in request.prompt(),
        "User locale: en" in request.prompt(),
        "First? (q1): Alpha" in request.prompt(),
        request.answers_text(),
    ) == (
        True,
        True,
        True,
        "q1-Alpha, q2-Beta",
    ), "prediction prompt omitted the current date, locale, or questionnaire answers"


def test_converts_days_left_into_an_absolute_death_date() -> None:
    stored = StoredDeathPrediction(
        request_id="request-3613",
        provider="yandex",
        consumes_quota=True,
        current_date=date(2026, 7, 30),
        prediction=DeathPrediction(days_left=17, message="Seventeen days"),
    )

    assert stored.death_date() == date(2026, 8, 16)
