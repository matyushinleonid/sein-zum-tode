import logging
from dataclasses import dataclass

from temporalio import activity

from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.ports import MortalSchedule
from sein_zum_tode.observability import LogContext

ENSURE_MORTAL_ACTIVITY_NAME = "ensure_mortal"
RESET_MORTAL_ACTIVITY_NAME = "reset_mortal"
CHECK_MORTAL_QUOTA_ACTIVITY_NAME = "check_mortal_llm_quota"
DEACTIVATE_MORTAL_ACTIVITY_NAME = "deactivate_mortal"
DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME = "delete_mortal_schedule"


@dataclass(frozen=True, slots=True)
class MortalActivityInput:
    mortal_id: int


class MortalActivities:
    def __init__(
        self,
        *,
        mortals: MortalRepository,
        schedules: MortalSchedule,
        logger: logging.Logger | None = None,
    ) -> None:
        self._mortals = mortals
        self._schedules = schedules
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=ENSURE_MORTAL_ACTIVITY_NAME)
    async def ensure(self, input: MortalActivityInput) -> None:
        await self._mortals.ensure(input.mortal_id)
        self._logger.info(
            "Mortal registered",
            extra=LogContext(component="worker", user_id=input.mortal_id).event(
                "mortal_registered"
            ),
        )

    @activity.defn(name=RESET_MORTAL_ACTIVITY_NAME)
    async def reset(self, input: MortalActivityInput) -> None:
        await self._mortals.reset(input.mortal_id)
        await self._schedules.delete(input.mortal_id)
        self._logger.info(
            "Mortal reset after Telegram unblock",
            extra=LogContext(component="worker", user_id=input.mortal_id).event("mortal_reset"),
        )

    @activity.defn(name=CHECK_MORTAL_QUOTA_ACTIVITY_NAME)
    async def has_quota(self, input: MortalActivityInput) -> bool:
        mortal = await self._mortals.get(input.mortal_id)
        return mortal is not None and mortal.can_request_prediction()

    @activity.defn(name=DEACTIVATE_MORTAL_ACTIVITY_NAME)
    async def deactivate(self, input: MortalActivityInput) -> None:
        await self._mortals.delete(input.mortal_id)
        await self._schedules.delete(input.mortal_id)
        self._logger.info(
            "Mortal deleted",
            extra=LogContext(component="worker", user_id=input.mortal_id).event("mortal_deleted"),
        )

    @activity.defn(name=DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME)
    async def delete_schedule(self, input: MortalActivityInput) -> None:
        await self._schedules.delete(input.mortal_id)
