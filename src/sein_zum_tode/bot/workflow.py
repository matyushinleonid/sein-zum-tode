from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_ECHO_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_UNSUPPORTED_ACTIVITY_NAME,
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TELEGRAM_USER_WORKFLOW_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    InspectUpdateInput,
    PrepareResponseInput,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.observability import LogContext

RECENT_UPDATE_KEYS_LIMIT = 256


@workflow.defn(name=TELEGRAM_USER_WORKFLOW_NAME)
class TelegramUserWorkflow:
    @workflow.init
    def __init__(self, input: UserWorkflowInput) -> None:
        self._user_id = input.user_id
        self._activity_timeout = timedelta(seconds=input.activity_retry_timeout_seconds)
        self._pending_update_keys = list(input.pending_update_keys)
        self._recent_update_keys = list(input.recent_update_keys)
        self._active_update_key: str | None = None
        self._continue_as_new_after_updates = input.continue_as_new_after_updates
        self._processed_since_continue = 0

    @workflow.signal(name=TELEGRAM_UPDATE_SIGNAL_NAME)
    def accept_update(self, input: TelegramUpdateSignal) -> None:
        if (
            input.redis_key == self._active_update_key
            or input.redis_key in self._pending_update_keys
            or input.redis_key in self._recent_update_keys
        ):
            return
        self._pending_update_keys.append(input.redis_key)

    @workflow.run
    async def run(self, input: UserWorkflowInput) -> None:
        while True:
            await workflow.wait_condition(lambda: bool(self._pending_update_keys))
            update_key = self._pending_update_keys.pop(0)
            self._active_update_key = update_key
            await self._process(update_key)
            self._active_update_key = None
            self._remember(update_key)
            self._processed_since_continue += 1
            await self._continue_as_new_if_needed()

    async def _process(self, update_key: str) -> None:
        response_key = f"{update_key}:response"
        try:
            inspected: InspectedUpdate = await workflow.execute_activity(
                INSPECT_UPDATE_ACTIVITY_NAME,
                InspectUpdateInput(update_key=update_key, user_id=self._user_id),
                result_type=InspectedUpdate,
                schedule_to_close_timeout=self._activity_timeout,
            )
            prepare_input = PrepareResponseInput(
                update_key=update_key,
                response_key=response_key,
                chat_id=inspected.chat_id,
                user_id=self._user_id,
            )
            await workflow.execute_activity(
                self._prepare_activity_name(inspected.kind),
                prepare_input,
                schedule_to_close_timeout=self._activity_timeout,
            )
            await workflow.execute_activity(
                DELIVER_RESPONSE_ACTIVITY_NAME,
                DeliverResponseInput(
                    response_key=response_key,
                    update_key=update_key,
                    user_id=self._user_id,
                ),
                schedule_to_close_timeout=self._activity_timeout,
            )
        except ActivityError:
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Telegram update processing failed",
                extra=context.event("telegram_update_processing_failed"),
            )
        finally:
            await self._cleanup(update_key, response_key)

    async def _cleanup(self, update_key: str, response_key: str) -> None:
        try:
            await workflow.execute_activity(
                CLEANUP_PAYLOADS_ACTIVITY_NAME,
                CleanupPayloadsInput(
                    keys=(update_key, response_key),
                    update_key=update_key,
                    user_id=self._user_id,
                ),
                schedule_to_close_timeout=self._activity_timeout,
            )
        except ActivityError:
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Telegram payload cleanup failed",
                extra=context.event(
                    "telegram_payload_cleanup_failed",
                    response_key=response_key,
                ),
            )

    def _prepare_activity_name(self, kind: InspectionKind) -> str:
        match kind:
            case InspectionKind.ECHO:
                return PREPARE_ECHO_ACTIVITY_NAME
            case InspectionKind.HELP:
                return PREPARE_HELP_ACTIVITY_NAME
            case InspectionKind.GROUP_UNSUPPORTED:
                return PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME
            case InspectionKind.UNSUPPORTED:
                return PREPARE_UNSUPPORTED_ACTIVITY_NAME

    def _remember(self, update_key: str) -> None:
        self._recent_update_keys.append(update_key)
        del self._recent_update_keys[:-RECENT_UPDATE_KEYS_LIMIT]

    async def _continue_as_new_if_needed(self) -> None:
        forced = (
            self._continue_as_new_after_updates is not None
            and self._processed_since_continue >= self._continue_as_new_after_updates
        )
        if not forced and not workflow.info().is_continue_as_new_suggested():
            return
        await workflow.wait_condition(workflow.all_handlers_finished)
        workflow.continue_as_new(
            UserWorkflowInput(
                user_id=self._user_id,
                activity_retry_timeout_seconds=int(self._activity_timeout.total_seconds()),
                pending_update_keys=tuple(self._pending_update_keys),
                recent_update_keys=tuple(self._recent_update_keys),
                continue_as_new_after_updates=self._continue_as_new_after_updates,
            )
        )
