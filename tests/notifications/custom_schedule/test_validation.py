from datetime import UTC, datetime, timedelta

import pytest

from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleSettings,
)
from sein_zum_tode.notifications.custom_schedule.validation import (
    InvalidNotificationScheduleError,
    NotificationScheduleTooFrequentError,
    NotificationScheduleValidator,
)

pytestmark = pytest.mark.fast


def validator() -> NotificationScheduleValidator:
    return NotificationScheduleValidator(minimum_interval=timedelta(hours=20))


@pytest.mark.parametrize("cron", [None, "0 9 * * *", "30 19 * * 1-5"])
def test_accepts_disabled_daily_or_sparser_schedules(cron: str | None) -> None:
    validator().validate(
        NotificationScheduleSettings(cron=cron, timezone="Europe/Berlin"),
        now=datetime(2026, 8, 1, 12, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("cron", "timezone"),
    [
        ("0 9 * *", "Europe/Moscow"),
        ("x x x x x", "Europe/Moscow"),
        ("0 9 * * *", "Mars/Olympus_Mons"),
    ],
)
def test_rejects_invalid_cron_or_timezone(cron: str, timezone: str) -> None:
    with pytest.raises(InvalidNotificationScheduleError):
        validator().validate(
            NotificationScheduleSettings(cron=cron, timezone=timezone),
            now=datetime(2026, 8, 1, 12, tzinfo=UTC),
        )


def test_rejects_a_schedule_that_runs_more_than_once_a_day() -> None:
    with pytest.raises(NotificationScheduleTooFrequentError):
        validator().validate(
            NotificationScheduleSettings(
                cron="0 9,21 * * *",
                timezone="Europe/Moscow",
            ),
            now=datetime(2026, 8, 1, 12, tzinfo=UTC),
        )


def test_requires_an_aware_validation_time() -> None:
    with pytest.raises(ValueError, match="timezone information"):
        validator().validate(
            NotificationScheduleSettings(
                cron="0 9 * * *",
                timezone="Europe/Moscow",
            ),
            now=datetime(2026, 8, 1, 12),
        )
