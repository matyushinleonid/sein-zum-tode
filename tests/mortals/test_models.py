from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from sein_zum_tode.mortals.models import Mortal

pytestmark = pytest.mark.fast


def test_uses_fixed_defaults_for_a_new_mortal() -> None:
    actual = Mortal(id=310_019)

    assert actual == Mortal(
        id=310_019,
        locale="en",
        timezone="Europe/Moscow",
        notification_cron="0 9 * * *",
        death_date=None,
    ), "new Mortal did not receive the approved locale, timezone, or notification cron"


def test_allows_a_mortal_to_disable_notifications() -> None:
    actual = Mortal(id=310_021, notification_cron=None)

    assert actual.notification_cron is None, (
        "nullable notification cron could not represent disabled notifications"
    )


def test_prediction_quota_is_available_only_above_zero() -> None:
    assert (
        Mortal(id=310_023).can_request_prediction(),
        Mortal(id=310_025, llm_requests_remaining=0).can_request_prediction(),
    ) == (True, False)


def test_rejects_an_unknown_iana_timezone() -> None:
    with pytest.raises(ValidationError):
        Mortal(id=310_027, timezone="Mars/Olympus_Mons")


def test_returns_no_countdown_without_a_death_date() -> None:
    actual = Mortal(id=310_043).days_left(datetime(2099, 12, 1, tzinfo=UTC))

    assert actual is None, "Mortal without a death date unexpectedly produced a notification"


def test_counts_calendar_days_in_the_mortal_timezone_and_clamps_the_past() -> None:
    mortal = Mortal(id=310_051, death_date=date(2100, 1, 1))

    before_local_midnight = mortal.days_left(datetime(2099, 12, 31, 20, 59, tzinfo=UTC))
    after_local_midnight = mortal.days_left(datetime(2099, 12, 31, 21, 1, tzinfo=UTC))
    past = mortal.days_left(datetime(2100, 1, 7, tzinfo=UTC))

    assert (before_local_midnight, after_local_midnight, past) == (1, 0, 0), (
        "countdown ignored the Mortal timezone or returned a negative day count"
    )


def test_rejects_a_naive_countdown_timestamp() -> None:
    mortal = Mortal(id=310_063, death_date=date(2100, 1, 1))

    with pytest.raises(ValueError, match="timezone"):
        mortal.days_left(datetime(2099, 12, 31))
