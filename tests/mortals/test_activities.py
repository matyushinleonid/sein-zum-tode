from datetime import date

import pytest

from sein_zum_tode.mortals.activities import (
    MortalActivities,
    MortalActivityInput,
    MortalRegistration,
)
from sein_zum_tode.mortals.models import Mortal
from tests.support import SilentLogger

pytestmark = pytest.mark.fast


class MortalRepositoryDouble:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    async def ensure(self, mortal_id: int) -> Mortal:
        self.events.append(("ensure", mortal_id))
        return Mortal(id=mortal_id)

    async def get(self, mortal_id: int) -> Mortal | None:
        self.events.append(("get", mortal_id))
        return Mortal(id=mortal_id)

    async def set_death_date(self, mortal_id: int, death_date: date) -> Mortal:
        self.events.append(("set_death_date", mortal_id, death_date))
        return Mortal(id=mortal_id, death_date=death_date)

    async def set_notification_cron(
        self,
        mortal_id: int,
        cron: str | None,
    ) -> Mortal:
        self.events.append(("set_notification_cron", mortal_id, cron))
        return Mortal(id=mortal_id, notification_cron=cron)

    async def set_notification_settings(
        self,
        mortal_id: int,
        *,
        cron: str | None,
        timezone: str,
    ) -> Mortal:
        self.events.append(("set_notification_settings", mortal_id, cron, timezone))
        return Mortal(id=mortal_id, notification_cron=cron, timezone=timezone)

    async def set_locale(self, mortal_id: int, locale: str) -> Mortal:
        self.events.append(("set_locale", mortal_id, locale))
        return Mortal(id=mortal_id, locale=locale)

    async def consume_llm_request(self, mortal_id: int, request_id: str) -> Mortal:
        self.events.append(("consume_llm_request", mortal_id, request_id))
        return Mortal(id=mortal_id, llm_requests_remaining=49)

    async def mark_unreachable(self, mortal_id: int) -> None:
        self.events.append(("mark_unreachable", mortal_id))


class MortalScheduleDouble:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    async def ensure(self, mortal: Mortal) -> None:
        self.events.append(("ensure_schedule", mortal))

    async def delete(self, mortal_id: int) -> None:
        self.events.append(("delete_schedule", mortal_id))


def activities(events: list[tuple[object, ...]]) -> MortalActivities:
    return MortalActivities(
        mortals=MortalRepositoryDouble(events),
        schedules=MortalScheduleDouble(events),
        logger=SilentLogger(),
    )


async def test_registers_a_mortal_and_restores_its_schedule() -> None:
    events: list[tuple[object, ...]] = []

    actual = await activities(events).ensure(MortalActivityInput(mortal_id=330_017))

    assert (actual, events) == (
        MortalRegistration(localization_required=True),
        [
            ("ensure", 330_017),
            ("ensure_schedule", Mortal(id=330_017)),
        ],
    ), "registration did not expose localization or restore notification delivery"


async def test_reports_whether_a_mortal_has_prediction_quota() -> None:
    events: list[tuple[object, ...]] = []

    actual = await activities(events).has_quota(MortalActivityInput(mortal_id=330_023))

    assert (actual, events) == (
        True,
        [("get", 330_023)],
    ), "quota check did not read the current Mortal limit"


async def test_marks_the_mortal_unreachable_before_removing_its_schedule() -> None:
    events: list[tuple[object, ...]] = []

    await activities(events).mark_unreachable(MortalActivityInput(mortal_id=330_029))

    assert events == [
        ("mark_unreachable", 330_029),
        ("delete_schedule", 330_029),
    ], "unreachable state was not persisted before removing its Temporal Schedule"


async def test_deletes_only_the_schedule_when_notification_workflow_is_terminal() -> None:
    events: list[tuple[object, ...]] = []

    await activities(events).delete_schedule(MortalActivityInput(mortal_id=330_037))

    assert events == [("delete_schedule", 330_037)], (
        "terminal notification deleted the Mortal row together with its Schedule"
    )
