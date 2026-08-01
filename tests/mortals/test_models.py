from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from sein_zum_tode.mortals.models import MortalRegistrationDefaults
from tests.support import mortal

pytestmark = pytest.mark.fast


def test_builds_a_new_mortal_from_registration_defaults() -> None:
    defaults = MortalRegistrationDefaults(
        timezone="Asia/Tokyo",
        notification_cron="17 8 * * *",
    )

    actual = defaults.mortal(310_019)

    assert actual == mortal(
        id=310_019,
        locale=None,
        timezone="Asia/Tokyo",
        notification_cron="17 8 * * *",
        death_date=None,
    ), "new Mortal ignored the configured registration defaults"


def test_allows_a_mortal_to_disable_notifications() -> None:
    actual = mortal(id=310_021, notification_cron=None)

    assert actual.notification_cron is None, (
        "nullable notification cron could not represent disabled notifications"
    )


def test_prediction_quota_is_available_only_above_zero() -> None:
    assert (
        mortal(id=310_023).can_request_llm(),
        mortal(id=310_025, llm_requests_remaining=0).can_request_llm(),
    ) == (True, False)


def test_rejects_an_unknown_iana_timezone() -> None:
    with pytest.raises(ValidationError):
        mortal(id=310_027, timezone="Mars/Olympus_Mons")


def test_rejects_an_unknown_default_registration_timezone() -> None:
    with pytest.raises(ValidationError):
        MortalRegistrationDefaults(
            timezone="Mars/Olympus_Mons",
            notification_cron="17 8 * * *",
        )


def test_returns_no_countdown_without_a_death_date() -> None:
    actual = mortal(id=310_043).days_left(datetime(2099, 12, 1, tzinfo=UTC))

    assert actual is None, "Mortal without a death date unexpectedly produced a notification"


def test_counts_calendar_days_in_the_mortal_timezone_and_clamps_the_past() -> None:
    current_mortal = mortal(id=310_051, death_date=date(2100, 1, 1))

    before_local_midnight = current_mortal.days_left(datetime(2099, 12, 31, 20, 59, tzinfo=UTC))
    after_local_midnight = current_mortal.days_left(datetime(2099, 12, 31, 21, 1, tzinfo=UTC))
    past = current_mortal.days_left(datetime(2100, 1, 7, tzinfo=UTC))

    assert (before_local_midnight, after_local_midnight, past) == (1, 0, 0), (
        "countdown ignored the Mortal timezone or returned a negative day count"
    )


def test_rejects_a_naive_countdown_timestamp() -> None:
    current_mortal = mortal(id=310_063, death_date=date(2100, 1, 1))

    with pytest.raises(ValueError, match="timezone"):
        current_mortal.days_left(datetime(2099, 12, 31))
