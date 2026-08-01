from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
)
from sein_zum_tode.broadcasts.models import (
    DELIVER_SCREAM_ACTIVITY_NAME,
    LIST_SCREAM_RECIPIENTS_ACTIVITY_NAME,
    PREPARE_SCREAM_REPORT_ACTIVITY_NAME,
    TELEGRAM_SCREAM_WORKFLOW_NAME,
    DeliverScreamInput,
    ListScreamRecipientsInput,
    PrepareScreamReportInput,
    ScreamRecipients,
    ScreamWorkflowInput,
)
from sein_zum_tode.mortals.activities import (
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
    MortalActivityInput,
)
from sein_zum_tode.observability import LogContext


@workflow.defn(name=TELEGRAM_SCREAM_WORKFLOW_NAME)
class TelegramScreamWorkflow:
    @workflow.run
    async def run(self, input: ScreamWorkflowInput) -> None:
        activity_timeout = timedelta(seconds=input.activity_retry_timeout_seconds)
        delivered = 0
        failed = 0
        cursor: int | None = None
        while True:
            recipients = await self._recipients(input, cursor, activity_timeout)
            if recipients is None:
                break
            for recipient_id in recipients.mortal_ids:
                if await self._deliver(input, recipient_id, activity_timeout):
                    delivered += 1
                else:
                    failed += 1
            cursor = recipients.next_cursor()
            if len(recipients.mortal_ids) < input.recipient_page_size:
                break
        await self._report(input, delivered, failed, activity_timeout)

    async def _recipients(
        self,
        input: ScreamWorkflowInput,
        cursor: int | None,
        activity_timeout: timedelta,
    ) -> ScreamRecipients | None:
        try:
            return cast(
                ScreamRecipients,
                await workflow.execute_activity(
                    LIST_SCREAM_RECIPIENTS_ACTIVITY_NAME,
                    ListScreamRecipientsInput(
                        locale=input.request.locale,
                        after_mortal_id=cursor,
                        limit=input.recipient_page_size,
                        admin_user_id=input.admin_user_id,
                        update_key=input.update_key,
                    ),
                    result_type=ScreamRecipients,
                    schedule_to_close_timeout=activity_timeout,
                ),
            )
        except ActivityError:
            workflow.logger.exception(
                "Scream recipient selection failed",
                extra=self._context(input).event(
                    "scream_recipient_selection_failed",
                    locale=input.request.locale,
                ),
            )
            return None

    async def _deliver(
        self,
        input: ScreamWorkflowInput,
        recipient_id: int,
        activity_timeout: timedelta,
    ) -> bool:
        try:
            await workflow.execute_activity(
                DELIVER_SCREAM_ACTIVITY_NAME,
                DeliverScreamInput(
                    request=input.request,
                    recipient_id=recipient_id,
                    admin_user_id=input.admin_user_id,
                    update_key=input.update_key,
                ),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError as error:
            if self._recipient_unavailable(error):
                await self._mark_unreachable(input, recipient_id, activity_timeout)
            workflow.logger.exception(
                "Scream delivery failed",
                extra=self._context(input).event(
                    "scream_delivery_failed",
                    recipient_id=recipient_id,
                    locale=input.request.locale,
                ),
            )
            return False
        return True

    async def _mark_unreachable(
        self,
        input: ScreamWorkflowInput,
        recipient_id: int,
        activity_timeout: timedelta,
    ) -> None:
        try:
            await workflow.execute_activity(
                MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
                MortalActivityInput(mortal_id=recipient_id),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError:
            workflow.logger.exception(
                "Failed to mark scream recipient unreachable",
                extra=self._context(input).event(
                    "scream_recipient_mark_unreachable_failed",
                    recipient_id=recipient_id,
                ),
            )

    async def _report(
        self,
        input: ScreamWorkflowInput,
        delivered: int,
        failed: int,
        activity_timeout: timedelta,
    ) -> None:
        response_key = f"{input.update_key}:scream-report"
        try:
            await workflow.execute_activity(
                PREPARE_SCREAM_REPORT_ACTIVITY_NAME,
                PrepareScreamReportInput(
                    response_key=response_key,
                    admin_chat_id=input.admin_chat_id,
                    admin_user_id=input.admin_user_id,
                    update_key=input.update_key,
                    delivered=delivered,
                    failed=failed,
                ),
                schedule_to_close_timeout=activity_timeout,
            )
            await workflow.execute_activity(
                DELIVER_RESPONSE_ACTIVITY_NAME,
                DeliverResponseInput(
                    response_key=response_key,
                    update_key=input.update_key,
                    user_id=input.admin_user_id,
                ),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError:
            workflow.logger.exception(
                "Scream report delivery failed",
                extra=self._context(input).event(
                    "scream_report_delivery_failed",
                    delivered=delivered,
                    failed=failed,
                ),
            )
        finally:
            await self._cleanup(input, response_key, activity_timeout)

    async def _cleanup(
        self,
        input: ScreamWorkflowInput,
        response_key: str,
        activity_timeout: timedelta,
    ) -> None:
        try:
            await workflow.execute_activity(
                CLEANUP_PAYLOADS_ACTIVITY_NAME,
                CleanupPayloadsInput(
                    keys=(input.update_key, response_key),
                    update_key=input.update_key,
                    user_id=input.admin_user_id,
                ),
                schedule_to_close_timeout=activity_timeout,
            )
        except ActivityError:
            workflow.logger.exception(
                "Scream payload cleanup failed",
                extra=self._context(input).event("scream_payload_cleanup_failed"),
            )

    def _context(self, input: ScreamWorkflowInput) -> LogContext:
        return LogContext(
            component="worker",
            user_id=input.admin_user_id,
            update_key=input.update_key,
        )

    def _recipient_unavailable(self, error: ActivityError) -> bool:
        cause = error.cause
        return isinstance(cause, ApplicationError) and cause.type == (
            "TelegramRecipientUnavailable"
        )
