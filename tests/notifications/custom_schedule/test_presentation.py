from datetime import UTC, datetime

import pytest

from sein_zum_tode.notifications.custom_schedule.config import NotificationPresets
from sein_zum_tode.notifications.custom_schedule.models import NotificationScheduleSettings
from sein_zum_tode.notifications.custom_schedule.presentation import (
    NotificationPresetPresenter,
    NotificationSchedulePresenter,
)
from sein_zum_tode.notifications.models import NotificationFrequency
from tests.support import BotContents

pytestmark = pytest.mark.fast


class DescriptionMemory:
    def __init__(self, description: str) -> None:
        self.description = description
        self.events: list[tuple[str, str]] = []

    def describe(self, expression: str, locale: str) -> str:
        self.events.append((expression, locale))
        return self.description


class BrokenDescription:
    def describe(self, expression: str, locale: str) -> str:
        raise RuntimeError(f"cannot describe {expression} in {locale}")


@pytest.mark.parametrize(
    ("frequency", "cron", "expected"),
    [
        (NotificationFrequency.DAILY, "7 9 * * *", "Daily · 09:07"),
        (NotificationFrequency.NEVER, None, "Never"),
        (NotificationFrequency.WEEKLY, "7 */3 * * 1", "Weekly"),
    ],
)
def test_adds_a_fixed_time_to_preset_labels(
    frequency: NotificationFrequency,
    cron: str | None,
    expected: str,
) -> None:
    daily = cron if frequency == NotificationFrequency.DAILY and cron is not None else "0 9 * * *"
    weekly = cron if frequency == NotificationFrequency.WEEKLY and cron is not None else "0 9 * * 1"
    presets = NotificationPresets(
        daily=daily,
        weekly=weekly,
        monthly="0 9 1 * *",
    )

    actual = NotificationPresetPresenter(presets).label(frequency, frequency.value.title())

    assert actual == expected, "preset button did not reflect its configured wall-clock time"


def test_presents_the_applied_schedule_and_three_local_occurrences() -> None:
    descriptions = DescriptionMemory("At 19:30, Monday through Friday")
    content = BotContents.debug().localized("en").notification_settings
    subject = NotificationSchedulePresenter(descriptions=descriptions)

    actual = subject.applied(
        explanation="Weekday evenings were selected.",
        settings=NotificationScheduleSettings(
            cron="30 19 * * 1-5",
            timezone="Europe/Berlin",
        ),
        locale="en",
        now=datetime(2026, 8, 1, 12, 7, tzinfo=UTC),
        content=content,
    )

    assert (
        actual,
        descriptions.events,
    ) == (
        (
            "The model interpreted your request as:\n"
            "Weekday evenings were selected.\n\n"
            "Applied schedule:\n"
            "Cron: 30 19 * * 1-5\n"
            "Description: At 19:30, Monday through Friday\n"
            "Timezone: Europe/Berlin\n\n"
            "Next notifications:\n"
            "• Mon, 3 Aug 2026, 19:30 (Europe/Berlin)\n"
            "• Tue, 4 Aug 2026, 19:30 (Europe/Berlin)\n"
            "• Wed, 5 Aug 2026, 19:30 (Europe/Berlin)\n\n"
            "Use /notifications to change it."
        ),
        [("30 19 * * 1-5", "en_US")],
    ), "schedule summary disagreed with the persisted cron, timezone, or next runs"


def test_presents_disabled_notifications_without_occurrences() -> None:
    content = BotContents.debug().localized("ru").notification_settings
    subject = NotificationSchedulePresenter(descriptions=DescriptionMemory("unused"))

    actual = subject.applied(
        explanation="Уведомления больше не нужны.",
        settings=NotificationScheduleSettings(cron=None, timezone="Europe/Moscow"),
        locale="ru",
        now=datetime(2026, 8, 1, 12, 7, tzinfo=UTC),
        content=content,
    )

    assert actual == (
        "Модель интерпретировала запрос так:\n"
        "Уведомления больше не нужны.\n\n"
        "Установленное расписание:\n"
        "Уведомления отключены.\n"
        "Часовой пояс: Europe/Moscow\n\n"
        "Используйте /notifications, чтобы изменить его."
    ), "disabled schedule included a fake cron or future notification time"


def test_falls_back_when_description_and_occurrence_rendering_fail() -> None:
    content = BotContents.debug().localized("en").notification_settings
    subject = NotificationSchedulePresenter(descriptions=BrokenDescription())

    actual = subject.applied(
        explanation="An unusual schedule was selected.",
        settings=NotificationScheduleSettings(cron="invalid", timezone="Invalid/Zone"),
        locale="unknown",
        now=datetime(2026, 8, 1, 12, 7, tzinfo=UTC),
        content=content,
    )

    assert (
        "Description: Description unavailable." in actual,
        "Next times unavailable." in actual,
    ) == (True, True), "presentation failure hid the applied cron and timezone without a warning"


def test_marks_a_rejected_schedule_as_unchanged() -> None:
    content = BotContents.debug().localized("en").notification_settings

    actual = NotificationSchedulePresenter(descriptions=DescriptionMemory("unused")).unchanged(
        "Please provide a time.", content
    )

    assert actual == "Please provide a time.\n\nThe schedule was not changed.", (
        "rejected schedule looked as though it had been applied"
    )


def test_truncates_the_model_explanation_before_the_authoritative_schedule() -> None:
    content = BotContents.debug().localized("en").notification_settings
    subject = NotificationSchedulePresenter(descriptions=DescriptionMemory("Daily at noon"))

    actual = subject.applied(
        explanation="x" * 4096,
        settings=NotificationScheduleSettings(
            cron="0 12 * * *",
            timezone="Europe/Moscow",
        ),
        locale="en",
        now=datetime(2026, 8, 1, 12, 7, tzinfo=UTC),
        content=content,
    )

    assert (
        len(actual),
        "Applied schedule:" in actual,
        actual.endswith("Use /notifications to change it."),
    ) == (4096, True, True), "long model text displaced the authoritative schedule summary"
