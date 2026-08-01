from datetime import date

import pytest
from pydantic import ValidationError

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
        prediction=DeathPrediction(
            prediction_possible=True,
            days_left=17,
            message="Seventeen days",
        ),
    )

    assert stored.death_date() == date(2026, 8, 16)


def test_keeps_an_impossible_prediction_without_a_death_date() -> None:
    stored = StoredDeathPrediction(
        request_id="request-3617",
        provider="openai",
        consumes_quota=True,
        current_date=date(2026, 7, 30),
        prediction=DeathPrediction(
            prediction_possible=False,
            days_left=None,
            message="Answers are not meaningful",
        ),
    )

    assert stored.death_date() is None


@pytest.mark.parametrize(
    ("prediction_possible", "days_left"),
    [(True, None), (False, 17)],
)
def test_rejects_a_prediction_flag_inconsistent_with_days(
    prediction_possible: bool,
    days_left: int | None,
) -> None:
    with pytest.raises(ValidationError):
        DeathPrediction(
            prediction_possible=prediction_possible,
            days_left=days_left,
            message="Inconsistent",
        )
