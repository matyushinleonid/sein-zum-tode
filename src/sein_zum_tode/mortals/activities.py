import logging
from dataclasses import dataclass

from temporalio import activity

from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.ports import MortalSchedule
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics

ENSURE_MORTAL_ACTIVITY_NAME = "ensure_mortal"
CHECK_MORTAL_QUOTA_ACTIVITY_NAME = "check_mortal_llm_quota"
MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME = "mark_mortal_unreachable"
DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME = "delete_mortal_schedule"


@dataclass(frozen=True, slots=True)
class MortalActivityInput:
    mortal_id: int


@dataclass(frozen=True, slots=True)
class MortalRegistration:
    localization_required: bool


class MortalActivities:
    def __init__(
        self,
        *,
        mortals: MortalRepository,
        schedules: MortalSchedule,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._mortals = mortals
        self._schedules = schedules
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=ENSURE_MORTAL_ACTIVITY_NAME)
    async def ensure(self, input: MortalActivityInput) -> MortalRegistration:
        previous = await self._mortals.get(input.mortal_id)
        mortal = await self._mortals.ensure(input.mortal_id)
        await self._schedules.ensure(mortal)
        event = (
            "registered"
            if previous is None
            else "reactivated"
            if previous.telegram_unreachable_at is not None
            else "ensured"
        )
        self._metrics.mortal(event=event)
        self._logger.info(
            "Mortal registration ensured",
            extra=LogContext(component="worker", user_id=input.mortal_id).event(f"mortal_{event}"),
        )
        return MortalRegistration(localization_required=mortal.locale is None)

    @activity.defn(name=CHECK_MORTAL_QUOTA_ACTIVITY_NAME)
    async def has_quota(self, input: MortalActivityInput) -> bool:
        mortal = await self._mortals.get(input.mortal_id)
        return mortal is not None and mortal.can_request_llm()

    @activity.defn(name=MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME)
    async def mark_unreachable(self, input: MortalActivityInput) -> None:
        await self._mortals.mark_unreachable(input.mortal_id)
        await self._schedules.delete(input.mortal_id)
        self._metrics.mortal(event="unreachable")
        self._logger.info(
            "Mortal marked unreachable",
            extra=LogContext(component="worker", user_id=input.mortal_id).event(
                "mortal_marked_unreachable"
            ),
        )

    @activity.defn(name=DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME)
    async def delete_schedule(self, input: MortalActivityInput) -> None:
        await self._schedules.delete(input.mortal_id)
        self._metrics.mortal(event="schedule_deleted")
