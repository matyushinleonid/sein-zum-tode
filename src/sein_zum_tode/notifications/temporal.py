from collections.abc import Callable
from typing import Protocol

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.models import (
    MORTAL_NOTIFICATION_WORKFLOW_NAME,
    MortalNotificationWorkflowInput,
)
from sein_zum_tode.notifications.ports import MortalSchedule


class TemporalScheduleHandle(Protocol):
    async def update(
        self,
        updater: Callable[[ScheduleUpdateInput], ScheduleUpdate | None],
    ) -> None: ...

    async def delete(self) -> None: ...


class TemporalScheduleClient(Protocol):
    async def create_schedule(
        self,
        id: str,
        schedule: Schedule,
    ) -> TemporalScheduleHandle: ...

    def get_schedule_handle(self, id: str) -> TemporalScheduleHandle: ...


class TemporalMortalSchedule(MortalSchedule):
    def __init__(
        self,
        *,
        client: TemporalScheduleClient,
        bot_id: int,
        task_queue: str,
        activity_retry_timeout_seconds: int,
    ) -> None:
        self._client = client
        self._bot_id = bot_id
        self._task_queue = task_queue
        self._activity_retry_timeout_seconds = activity_retry_timeout_seconds

    async def ensure(self, mortal: Mortal) -> None:
        if mortal.notification_cron is None or mortal.death_date is None:
            await self.delete(mortal.id)
            return
        schedule_id = self._schedule_id(mortal.id)
        schedule = self._schedule(mortal, mortal.notification_cron)
        try:
            await self._client.create_schedule(schedule_id, schedule)
        except ScheduleAlreadyRunningError:
            handle = self._client.get_schedule_handle(schedule_id)
            await handle.update(self._updater(schedule))

    async def delete(self, mortal_id: int) -> None:
        try:
            await self._client.get_schedule_handle(self._schedule_id(mortal_id)).delete()
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise

    def _schedule_id(self, mortal_id: int) -> str:
        return f"telegram-notification:{self._bot_id}:{mortal_id}"

    def _schedule(self, mortal: Mortal, cron: str) -> Schedule:
        return Schedule(
            action=ScheduleActionStartWorkflow(
                MORTAL_NOTIFICATION_WORKFLOW_NAME,
                MortalNotificationWorkflowInput(
                    mortal_id=mortal.id,
                    activity_retry_timeout_seconds=self._activity_retry_timeout_seconds,
                ),
                id=self._schedule_id(mortal.id),
                task_queue=self._task_queue,
            ),
            spec=ScheduleSpec(
                cron_expressions=[cron],
                time_zone_name=mortal.timezone,
            ),
        )

    def _updater(
        self,
        schedule: Schedule,
    ) -> Callable[[ScheduleUpdateInput], ScheduleUpdate | None]:
        def update(_: ScheduleUpdateInput) -> ScheduleUpdate:
            return ScheduleUpdate(schedule=schedule)

        return update
