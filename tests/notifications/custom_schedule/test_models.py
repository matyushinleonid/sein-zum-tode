from datetime import datetime

import pytest

from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleProposal,
    NotificationScheduleRequest,
    NotificationScheduleSettings,
)

pytestmark = pytest.mark.fast


def test_requires_the_complete_final_state_in_the_structured_output_schema() -> None:
    assert set(NotificationScheduleProposal.model_json_schema()["required"]) == {
        "understood",
        "cron",
        "timezone",
        "explanation",
    }, "structured output must always contain the complete proposed schedule state"


def test_exposes_the_complete_disabled_schedule_proposed_by_the_model() -> None:
    proposal = NotificationScheduleProposal(
        understood=True,
        cron=None,
        timezone="Asia/Tokyo",
        explanation="Notifications disabled in the new timezone.",
    )

    actual = proposal.settings()

    assert actual == NotificationScheduleSettings(
        cron=None,
        timezone="Asia/Tokyo",
    ), "disabled final state was not preserved"


def test_exposes_the_complete_enabled_schedule_proposed_by_the_model() -> None:
    proposal = NotificationScheduleProposal(
        understood=True,
        cron="30 19 * * 1-5",
        timezone="Europe/Berlin",
        explanation="Weekday notifications configured.",
    )

    actual = proposal.settings()

    assert actual == NotificationScheduleSettings(
        cron="30 19 * * 1-5",
        timezone="Europe/Berlin",
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
        "Required language for the explanation field: ru" in prompt,
        "Current notification cron: disabled" in prompt,
        "Current IANA timezone: Europe/Moscow" in prompt,
        "2026-08-01T15:17:00+03:00" in prompt,
        "User request: По будням вечером" in prompt,
    ) == (True, True, True, True, True), (
        "schedule prompt omitted locale, current settings, local time, or user request"
    )
