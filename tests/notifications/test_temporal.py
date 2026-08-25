from collections.abc import Callable
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleDescription,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from sein_zum_tode.notifications.models import MortalNotificationWorkflowInput
from sein_zum_tode.notifications.temporal import (
    TemporalMortalSchedule,
    TemporalScheduleHandle,
)
from tests.support import mortal

pytestmark = pytest.mark.fast


def result_or_raise(value: object) -> object:
    if isinstance(value, BaseException):
        raise value
    return value


class ScheduleHandleDouble:
    def __init__(
        self,
        delete_outcome: object = None,
        *,
        update_outcome: object = None,
        described_schedule: Schedule | None = None,
        next_action_times: tuple[datetime, ...] = (),
    ) -> None:
        self.delete_outcome = delete_outcome
        self.update_outcome = update_outcome
        self.described_schedule = described_schedule
        self.next_action_times = next_action_times
        self.events: list[tuple[object, ...]] = []
        self.updated_schedule: Schedule | None = None

    async def update(
        self,
        updater: Callable[[ScheduleUpdateInput], ScheduleUpdate | None],
    ) -> None:
        self.events.append(("update",))
        result_or_raise(self.update_outcome)
        input = (
            object.__new__(ScheduleUpdateInput)
            if self.described_schedule is None
            else cast(
                ScheduleUpdateInput,
                SimpleNamespace(
                    description=SimpleNamespace(schedule=self.described_schedule),
                ),
            )
        )
        update = updater(input)
        self.updated_schedule = update.schedule if update is not None else None
        if self.updated_schedule is not None:
            self.described_schedule = self.updated_schedule

    async def describe(self) -> ScheduleDescription:
        self.events.append(("describe",))
        return cast(
            ScheduleDescription,
            SimpleNamespace(
                schedule=self.described_schedule,
                info=SimpleNamespace(next_action_times=list(self.next_action_times)),
            ),
        )

    async def delete(self) -> None:
        self.events.append(("delete",))
        result_or_raise(self.delete_outcome)


class ScheduleClientDouble:
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


def mortal_schedule(client: ScheduleClientDouble) -> TemporalMortalSchedule:
    return TemporalMortalSchedule(
        client=client,
        bot_id=350_003,
        task_queue="mortal-notifications-3509",
        activity_retry_timeout_seconds=3511,
    )


async def test_creates_a_timezone_aware_daily_schedule() -> None:
    client = ScheduleClientDouble()
    current_mortal = mortal(
        id=350_023,
        notification_cron="17 9 * * *",
        death_date=date(2100, 1, 1),
    )

    await mortal_schedule(client).ensure(current_mortal)

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
        created.policy.overlap,
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
        ScheduleOverlapPolicy.CANCEL_OTHER,
    ), "Schedule projection lost Mortal cron, timezone, workflow id, or input"


async def test_updates_an_existing_schedule_idempotently() -> None:
    handle = ScheduleHandleDouble()
    client = ScheduleClientDouble(
        create_outcome=ScheduleAlreadyRunningError(),
        handle=handle,
    )
    current_mortal = mortal(
        id=350_027,
        notification_cron="23 10 * * *",
        death_date=date(2100, 1, 1),
    )

    await mortal_schedule(client).ensure(current_mortal)

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

    await mortal_schedule(client).ensure(mortal(id=350_033, notification_cron=None))

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

    await mortal_schedule(client).delete(350_039)

    assert handle.events == [("delete",)], (
        "Schedule deletion did not attempt the stable Mortal schedule id"
    )


async def test_propagates_a_schedule_deletion_transport_failure() -> None:
    failure = RPCError("Temporal unavailable", RPCStatusCode.UNAVAILABLE, b"unavailable")
    client = ScheduleClientDouble(handle=ScheduleHandleDouble(delete_outcome=failure))

    with pytest.raises(RPCError) as raised:
        await mortal_schedule(client).delete(350_041)

    assert raised.value is failure


async def test_returns_the_earliest_next_action_and_migrates_overlap_policy() -> None:
    existing = Schedule(
        action=ScheduleActionStartWorkflow(
            "OldNotificationWorkflow",
            id="old-notification-workflow",
            task_queue="old-notification-queue",
        ),
        spec=ScheduleSpec(cron_expressions=["0 9 * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    later = datetime(2100, 1, 3, 9, 0, tzinfo=UTC)
    earlier = datetime(2100, 1, 2, 9, 0, tzinfo=UTC)
    handle = ScheduleHandleDouble(
        described_schedule=existing,
        next_action_times=(later, earlier),
    )
    client = ScheduleClientDouble(handle=handle)

    actual = await mortal_schedule(client).next_action_time(350_043)

    assert (
        actual,
        client.events,
        handle.events,
        cast(Schedule, handle.updated_schedule).policy.overlap,
    ) == (
        earlier,
        [("get_schedule_handle", "telegram-notification:350003:350043")],
        [("update",), ("describe",)],
        ScheduleOverlapPolicy.CANCEL_OTHER,
    ), "delivery planning lost the earliest action or left the old overlap policy active"


async def test_returns_no_next_action_for_a_missing_schedule() -> None:
    missing = RPCError("missing schedule", RPCStatusCode.NOT_FOUND, b"not-found")
    handle = ScheduleHandleDouble(update_outcome=missing)
    client = ScheduleClientDouble(handle=handle)

    actual = await mortal_schedule(client).next_action_time(350_047)

    assert (
        actual,
        handle.events,
    ) == (
        None,
        [("update",)],
    ), "missing Schedule was not treated as having no future notification action"


async def test_propagates_a_next_action_transport_failure() -> None:
    failure = RPCError("Temporal unavailable", RPCStatusCode.UNAVAILABLE, b"unavailable")
    client = ScheduleClientDouble(
        handle=ScheduleHandleDouble(update_outcome=failure),
    )

    with pytest.raises(RPCError) as raised:
        await mortal_schedule(client).next_action_time(350_053)

    assert raised.value is failure


async def test_keeps_an_existing_cancel_other_policy_unchanged() -> None:
    existing = Schedule(
        action=ScheduleActionStartWorkflow(
            "CurrentNotificationWorkflow",
            id="current-notification-workflow",
            task_queue="current-notification-queue",
        ),
        spec=ScheduleSpec(cron_expressions=["0 9 * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.CANCEL_OTHER),
    )
    next_action = datetime(2100, 1, 4, 9, 0, tzinfo=UTC)
    handle = ScheduleHandleDouble(
        described_schedule=existing,
        next_action_times=(next_action,),
    )
    client = ScheduleClientDouble(handle=handle)

    actual = await mortal_schedule(client).next_action_time(350_059)

    assert (
        actual,
        handle.updated_schedule,
        handle.events,
    ) == (
        next_action,
        None,
        [("update",), ("describe",)],
    ), "delivery planning rewrote an already-correct Schedule policy"
