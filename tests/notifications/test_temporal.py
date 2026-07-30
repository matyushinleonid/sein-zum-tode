from collections.abc import Callable
from datetime import date
from typing import cast

import pytest
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.models import MortalNotificationWorkflowInput
from sein_zum_tode.notifications.temporal import (
    TemporalMortalSchedule,
    TemporalScheduleClient,
    TemporalScheduleHandle,
)

pytestmark = pytest.mark.fast


def result_or_raise(value: object) -> object:
    if isinstance(value, BaseException):
        raise value
    return value


class ScheduleHandleDouble(TemporalScheduleHandle):
    def __init__(self, delete_outcome: object = None) -> None:
        self.delete_outcome = delete_outcome
        self.events: list[tuple[object, ...]] = []
        self.updated_schedule: Schedule | None = None

    async def update(
        self,
        updater: Callable[[ScheduleUpdateInput], ScheduleUpdate | None],
    ) -> None:
        self.events.append(("update",))
        update = updater(object.__new__(ScheduleUpdateInput))
        self.updated_schedule = update.schedule if update is not None else None

    async def delete(self) -> None:
        self.events.append(("delete",))
        result_or_raise(self.delete_outcome)


class ScheduleClientDouble(TemporalScheduleClient):
    def __init__(
        self,
        *,
        create_outcome: object = None,
        handle: ScheduleHandleDouble | None = None,
    ) -> None:
        self.create_outcome = create_outcome
        self.schedule_handle = handle or ScheduleHandleDouble()
        self.events: list[tuple[object, ...]] = []
        self.created_schedule: Schedule | None = None

    async def create_schedule(
        self,
        id: str,
        schedule: Schedule,
    ) -> TemporalScheduleHandle:
        self.events.append(("create_schedule", id))
        self.created_schedule = schedule
        result_or_raise(self.create_outcome)
        return self.schedule_handle

    def get_schedule_handle(self, id: str) -> TemporalScheduleHandle:
        self.events.append(("get_schedule_handle", id))
        return self.schedule_handle


def schedule(client: ScheduleClientDouble) -> TemporalMortalSchedule:
    return TemporalMortalSchedule(
        client=client,
        bot_id=350_003,
        task_queue="mortal-notifications-3509",
        activity_retry_timeout_seconds=3511,
    )


async def test_creates_a_timezone_aware_daily_schedule() -> None:
    client = ScheduleClientDouble()
    mortal = Mortal(
        id=350_023,
        notification_cron="17 9 * * *",
        death_date=date(2100, 1, 1),
    )

    await schedule(client).ensure(mortal)

    created = cast(Schedule, client.created_schedule)
    action = cast(ScheduleActionStartWorkflow, created.action)
    assert (
        client.events,
        created.spec.cron_expressions,
        created.spec.time_zone_name,
        action.workflow,
        action.id,
        action.task_queue,
        action.args,
    ) == (
        [("create_schedule", "telegram-notification:350003:350023")],
        ["17 9 * * *"],
        "Europe/Moscow",
        "MortalNotificationWorkflow",
        "telegram-notification:350003:350023",
        "mortal-notifications-3509",
        [
            MortalNotificationWorkflowInput(
                mortal_id=350_023,
                activity_retry_timeout_seconds=3511,
            )
        ],
    ), "Schedule projection lost Mortal cron, timezone, workflow id, or input"


async def test_updates_an_existing_schedule_idempotently() -> None:
    handle = ScheduleHandleDouble()
    client = ScheduleClientDouble(
        create_outcome=ScheduleAlreadyRunningError(),
        handle=handle,
    )
    mortal = Mortal(
        id=350_027,
        notification_cron="23 10 * * *",
        death_date=date(2100, 1, 1),
    )

    await schedule(client).ensure(mortal)

    assert (
        client.events,
        handle.events,
        cast(Schedule, handle.updated_schedule).spec.cron_expressions,
    ) == (
        [
            ("create_schedule", "telegram-notification:350003:350027"),
            ("get_schedule_handle", "telegram-notification:350003:350027"),
        ],
        [("update",)],
        ["23 10 * * *"],
    ), "existing Schedule was neither updated nor kept under its stable id"


async def test_null_cron_deletes_instead_of_creating_a_schedule() -> None:
    client = ScheduleClientDouble()

    await schedule(client).ensure(Mortal(id=350_033, notification_cron=None))

    assert (
        client.events,
        client.schedule_handle.events,
    ) == (
        [("get_schedule_handle", "telegram-notification:350003:350033")],
        [("delete",)],
    ), "disabled notifications left or recreated a Temporal Schedule"


@pytest.mark.parametrize(
    "delete_outcome",
    [
        None,
        RPCError("missing schedule", RPCStatusCode.NOT_FOUND, b"not-found"),
    ],
)
async def test_deletion_is_idempotent(delete_outcome: object) -> None:
    handle = ScheduleHandleDouble(delete_outcome=delete_outcome)
    client = ScheduleClientDouble(handle=handle)

    await schedule(client).delete(350_039)

    assert handle.events == [("delete",)], (
        "Schedule deletion did not attempt the stable Mortal schedule id"
    )


async def test_propagates_a_schedule_deletion_transport_failure() -> None:
    failure = RPCError("Temporal unavailable", RPCStatusCode.UNAVAILABLE, b"unavailable")
    client = ScheduleClientDouble(handle=ScheduleHandleDouble(delete_outcome=failure))

    with pytest.raises(RPCError) as raised:
        await schedule(client).delete(350_041)

    assert raised.value is failure
