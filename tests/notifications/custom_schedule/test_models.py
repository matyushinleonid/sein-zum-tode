from collections.abc import Callable
from datetime import datetime

import pytest
from pydantic import ValidationError

from sein_zum_tode.notifications.custom_schedule.models import (
    CronChange,
    CronOperation,
    NotificationScheduleProposal,
    NotificationScheduleRequest,
    NotificationScheduleSettings,
    TimezoneChange,
    TimezoneOperation,
)

pytestmark = pytest.mark.fast


def test_resolves_only_the_settings_selected_by_the_model() -> None:
    proposal = NotificationScheduleProposal(
        understood=True,
        cron=CronChange(operation=CronOperation.DISABLE),
        timezone=TimezoneChange(
            operation=TimezoneOperation.SET,
            value="Asia/Tokyo",
        ),
        message="Notifications disabled in the new timezone.",
    )

    actual = proposal.resolve(
        current_cron="0 9 * * *",
        current_timezone="Europe/Moscow",
    )

    assert actual == NotificationScheduleSettings(
        cron=None,
        timezone="Asia/Tokyo",
    ), "proposal resolution changed a value outside the requested operations"


def test_keeps_unmentioned_settings_while_setting_a_new_cron() -> None:
    proposal = NotificationScheduleProposal(
        understood=True,
        cron=CronChange(operation=CronOperation.SET, value="30 19 * * 1-5"),
        timezone=TimezoneChange(operation=TimezoneOperation.KEEP),
        message="Weekday notifications configured.",
    )

    actual = proposal.resolve(
        current_cron="0 9 * * *",
        current_timezone="Europe/Berlin",
    )

    assert actual == NotificationScheduleSettings(
        cron="30 19 * * 1-5",
        timezone="Europe/Berlin",
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda: CronChange(operation=CronOperation.SET),
        lambda: CronChange(operation=CronOperation.KEEP, value="0 9 * * *"),
        lambda: TimezoneChange(operation=TimezoneOperation.SET),
        lambda: TimezoneChange(
            operation=TimezoneOperation.KEEP,
            value="Europe/Moscow",
        ),
    ],
)
def test_rejects_operation_value_mismatches(change: Callable[[], object]) -> None:
    with pytest.raises(ValidationError):
        change()


@pytest.mark.parametrize("understood", [False, True])
def test_rejects_inconsistent_proposal_outcomes(understood: bool) -> None:
    cron = (
        CronChange(operation=CronOperation.SET, value="0 9 * * *")
        if not understood
        else CronChange(operation=CronOperation.KEEP)
    )

    with pytest.raises(ValidationError):
        NotificationScheduleProposal(
            understood=understood,
            cron=cron,
            timezone=TimezoneChange(operation=TimezoneOperation.KEEP),
            message="Inconsistent",
        )


def test_builds_a_localized_contextual_schedule_prompt() -> None:
    request = NotificationScheduleRequest(
        locale="ru",
        current_cron=None,
        current_timezone="Europe/Moscow",
        current_local_datetime=datetime.fromisoformat("2026-08-01T15:17:00+03:00"),
        user_request="По будням вечером",
    )

    prompt = request.prompt()

    assert (
        "Required language for the message field: ru" in prompt,
        "Current notification cron: disabled" in prompt,
        "Current IANA timezone: Europe/Moscow" in prompt,
        "2026-08-01T15:17:00+03:00" in prompt,
        "User request: По будням вечером" in prompt,
    ) == (True, True, True, True, True), (
        "schedule prompt omitted locale, current settings, local time, or user request"
    )
