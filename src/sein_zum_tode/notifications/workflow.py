from datetime import datetime, timedelta
from typing import cast

from temporalio import workflow
from temporalio.exceptions import ActivityError

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_NOTIFICATION_RESPONSE_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    DeliveryKind,
    PayloadKind,
    PreparedResponseDeliveryOutcome,
)
from sein_zum_tode.bot.temporal_errors import is_telegram_recipient_unavailable
from sein_zum_tode.mortals.activities import (
    DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
    MortalActivityInput,
)
from sein_zum_tode.notifications.models import (
    MORTAL_NOTIFICATION_WORKFLOW_NAME,
    PLAN_MORTAL_NOTIFICATION_DELIVERY_ACTIVITY_NAME,
    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
    MortalNotificationDeliveryPlan,
    MortalNotificationWorkflowInput,
    PlanMortalNotificationDeliveryInput,
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
)
from sein_zum_tode.observability import LogContext
from sein_zum_tode.payload_keys import MortalNotificationPayloadKeys


@workflow.defn(name=MORTAL_NOTIFICATION_WORKFLOW_NAME)
class MortalNotificationWorkflow:
    @workflow.run
    async def run(self, input: MortalNotificationWorkflowInput) -> None:
        if workflow.patched("durable-mortal-notification-v1"):
            await self._run_durable(input)
            return
        await self._run_legacy(input)

    async def _run_legacy(self, input: MortalNotificationWorkflowInput) -> None:
        activity_timeout = timedelta(seconds=input.activity_retry_timeout_seconds)
        response_key = MortalNotificationPayloadKeys(
            mortal_id=input.mortal_id,
            run_id=workflow.info().run_id,
        ).response()
        prepared = await self._prepare(input.mortal_id, response_key, activity_timeout)
        if prepared is None:
            await self._delete_schedule(input.mortal_id, activity_timeout)
            await self._cleanup(input.mortal_id, response_key, activity_timeout)
            return

        delivered = await self._deliver(
            input.mortal_id,
            prepared.response_key,
            activity_timeout,
        )
        await self._cleanup(input.mortal_id, prepared.response_key, activity_timeout)
        if delivered and prepared.terminal():
            await self._delete_schedule(input.mortal_id, activity_timeout)

    async def _run_durable(self, input: MortalNotificationWorkflowInput) -> None:
        activity_timeout = timedelta(seconds=input.activity_retry_timeout_seconds)
        deadline = input.parsed_delivery_deadline()
        if deadline is None:
            plan = await self._plan(input.mortal_id, activity_timeout)
            if plan is None:
                return
            deadline = plan.parsed_delivery_deadline()
        response_key = MortalNotificationPayloadKeys(
            mortal_id=input.mortal_id,
            run_id=workflow.info().run_id,
        ).response()
        while workflow.now() < deadline:
            try:
                prepared = await self._prepare_before(
                    input.mortal_id,
                    response_key,
                    activity_timeout,
                    deadline,
                )
            except ActivityError:
                self._log_failure(input.mortal_id, "mortal_notification_preparation_failed")
                raise
            if prepared is None:
                await self._delete_schedule(input.mortal_id, activity_timeout)
                await self._cleanup(input.mortal_id, response_key, activity_timeout)
                return
            outcome = await self._deliver_before(
                input.mortal_id,
                prepared.response_key,
                activity_timeout,
                deadline,
            )
            if outcome is None:
                await self._cleanup(input.mortal_id, prepared.response_key, activity_timeout)
                return
            if outcome == PreparedResponseDeliveryOutcome.DELIVERED:
                await self._cleanup(input.mortal_id, prepared.response_key, activity_timeout)
                if prepared.terminal():
                    await self._delete_schedule(input.mortal_id, activity_timeout)
                return
            self._continue_as_new_if_suggested(input, deadline)
        self._log_deadline_reached(input.mortal_id, deadline)

    async def _plan(
        self,
        mortal_id: int,
        activity_timeout: timedelta,
    ) -> MortalNotificationDeliveryPlan | None:
        try:
            return cast(
                MortalNotificationDeliveryPlan | None,
                await workflow.execute_activity(
                    PLAN_MORTAL_NOTIFICATION_DELIVERY_ACTIVITY_NAME,
                    PlanMortalNotificationDeliveryInput(mortal_id=mortal_id),
                    result_type=MortalNotificationDeliveryPlan,
                    start_to_close_timeout=activity_timeout,
                ),
            )
        except ActivityError:
            self._log_failure(mortal_id, "mortal_notification_delivery_planning_failed")
            raise

    async def _prepare_before(
        self,
        mortal_id: int,
        response_key: str,
        activity_timeout: timedelta,
        deadline: datetime,
    ) -> PreparedMortalNotification | None:
        remaining = max(
            deadline - workflow.now(),
            timedelta(microseconds=1),
        )
        return cast(
            PreparedMortalNotification | None,
            await workflow.execute_activity(
                PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
                PrepareMortalNotificationInput(
                    mortal_id=mortal_id,
                    response_key=response_key,
                ),
                result_type=PreparedMortalNotification,
                start_to_close_timeout=min(activity_timeout, remaining),
                schedule_to_close_timeout=remaining,
            ),
        )

    async def _deliver_before(
        self,
        mortal_id: int,
        response_key: str,
        activity_timeout: timedelta,
        deadline: datetime,
    ) -> PreparedResponseDeliveryOutcome | None:
        remaining = max(
            deadline - workflow.now(),
            timedelta(microseconds=1),
        )
        try:
            return cast(
                PreparedResponseDeliveryOutcome,
                await workflow.execute_activity(
                    DELIVER_NOTIFICATION_RESPONSE_ACTIVITY_NAME,
                    DeliverResponseInput(
                        response_key=response_key,
                        user_id=mortal_id,
                        delivery_kind=DeliveryKind.NOTIFICATION,
                    ),
                    result_type=PreparedResponseDeliveryOutcome,
                    start_to_close_timeout=min(activity_timeout, remaining),
                    schedule_to_close_timeout=remaining,
                ),
            )
        except ActivityError as error:
            if self._recipient_unavailable(error):
                await self._mark_unreachable(mortal_id, activity_timeout)
            self._log_failure(mortal_id, "mortal_notification_delivery_failed")
            return None

    async def _prepare(
        self,
        mortal_id: int,
        response_key: str,
        activity_timeout: timedelta,
    ) -> PreparedMortalNotification | None:
        try:
            return cast(
                PreparedMortalNotification | None,
                await workflow.execute_activity(
                    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
                    PrepareMortalNotificationInput(
                        mortal_id=mortal_id,
                        response_key=response_key,
                    ),
                    result_type=PreparedMortalNotification,
                    schedule_to_close_timeout=activity_timeout,
                ),
            )
        except ActivityError:
            self._log_failure(mortal_id, "mortal_notification_preparation_failed")
            raise

    async def _deliver(
        self,
        mortal_id: int,
        response_key: str,
        activity_timeout: timedelta,
    ) -> bool:
        try:
            await workflow.execute_activity(
                DELIVER_RESPONSE_ACTIVITY_NAME,
                DeliverResponseInput(
                    response_key=response_key,
                    user_id=mortal_id,
                    delivery_kind=DeliveryKind.NOTIFICATION,
                ),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError as error:
            if self._recipient_unavailable(error):
                await self._mark_unreachable(mortal_id, activity_timeout)
            self._log_failure(mortal_id, "mortal_notification_delivery_failed")
            return False
        return True

    async def _cleanup(
        self,
        mortal_id: int,
        response_key: str,
        activity_timeout: timedelta,
    ) -> None:
        try:
            await workflow.execute_activity(
                CLEANUP_PAYLOADS_ACTIVITY_NAME,
                CleanupPayloadsInput(
                    keys=(response_key,),
                    user_id=mortal_id,
                    payload_kind=PayloadKind.NOTIFICATION,
                ),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError:
            self._log_failure(mortal_id, "mortal_notification_cleanup_failed")

    async def _mark_unreachable(
        self,
        mortal_id: int,
        activity_timeout: timedelta,
    ) -> None:
        try:
            await workflow.execute_activity(
                MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
                MortalActivityInput(mortal_id=mortal_id),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError:
            self._log_failure(mortal_id, "mortal_mark_unreachable_failed")

    async def _delete_schedule(
        self,
        mortal_id: int,
        activity_timeout: timedelta,
    ) -> None:
        try:
            await workflow.execute_activity(
                DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
                MortalActivityInput(mortal_id=mortal_id),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError:
            self._log_failure(mortal_id, "mortal_schedule_deletion_failed")

    def _recipient_unavailable(self, error: ActivityError) -> bool:
        return is_telegram_recipient_unavailable(error)

    def _continue_as_new_if_suggested(
        self,
        input: MortalNotificationWorkflowInput,
        deadline: datetime,
    ) -> None:
        if workflow.info().is_continue_as_new_suggested():
            workflow.continue_as_new(
                input.with_delivery_deadline(deadline),
            )

    def _log_failure(self, mortal_id: int, event: str) -> None:
        workflow.logger.exception(
            "Mortal notification processing failed",
            extra=LogContext(component="worker", user_id=mortal_id).event(event),
        )

    def _log_deadline_reached(self, mortal_id: int, deadline: datetime) -> None:
        workflow.logger.warning(
            "Mortal notification delivery deadline reached",
            extra=LogContext(component="worker", user_id=mortal_id).event(
                "mortal_notification_delivery_deadline_reached",
                delivery_deadline=deadline.isoformat(),
            ),
        )
