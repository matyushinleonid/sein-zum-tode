from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.exceptions import ActivityError

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    DeliveryKind,
    PayloadKind,
)
from sein_zum_tode.bot.temporal_errors import is_telegram_recipient_unavailable
from sein_zum_tode.mortals.activities import (
    DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
    MortalActivityInput,
)
from sein_zum_tode.notifications.models import (
    MORTAL_NOTIFICATION_WORKFLOW_NAME,
    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
    MortalNotificationWorkflowInput,
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
)
from sein_zum_tode.observability import LogContext
from sein_zum_tode.payload_keys import MortalNotificationPayloadKeys


@workflow.defn(name=MORTAL_NOTIFICATION_WORKFLOW_NAME)
class MortalNotificationWorkflow:
    @workflow.run
    async def run(self, input: MortalNotificationWorkflowInput) -> None:
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

    def _log_failure(self, mortal_id: int, event: str) -> None:
        workflow.logger.exception(
            "Mortal notification processing failed",
            extra=LogContext(component="worker", user_id=mortal_id).event(event),
        )
