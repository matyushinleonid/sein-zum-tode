import asyncio
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError

from sein_zum_tode.bot.conversation.models import (
    CONVERSATION_FINISHED_SIGNAL_NAME,
    CONVERSATION_UPDATE_SIGNAL_NAME,
    TELEGRAM_CONVERSATION_WORKFLOW_NAME,
    ConversationFinishedSignal,
    ConversationUpdateSignal,
    ConversationWorkflowInput,
)
from sein_zum_tode.bot.conversation.workflow import TelegramConversationWorkflow
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_ABOUT_ACTIVITY_NAME,
    PREPARE_ECHO_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    PREPARE_NOTIFICATIONS_ACTIVITY_NAME,
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
from sein_zum_tode.mortals.activities import (
    CHECK_MORTAL_QUOTA_ACTIVITY_NAME,
    DEACTIVATE_MORTAL_ACTIVITY_NAME,
    ENSURE_MORTAL_ACTIVITY_NAME,
    RESET_MORTAL_ACTIVITY_NAME,
    MortalActivityInput,
)
from sein_zum_tode.notifications.models import (
    CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME,
)
from sein_zum_tode.observability import LogContext

RECENT_UPDATE_KEYS_LIMIT = 256
PREPARE_ACTIVITY_NAMES = {
    InspectionKind.ECHO: PREPARE_ECHO_ACTIVITY_NAME,
    InspectionKind.HELP: PREPARE_HELP_ACTIVITY_NAME,
    InspectionKind.ABOUT: PREPARE_ABOUT_ACTIVITY_NAME,
    InspectionKind.NOTIFICATIONS: PREPARE_NOTIFICATIONS_ACTIVITY_NAME,
    InspectionKind.NOTIFICATION_SELECTION: CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME,
    InspectionKind.LIMIT_EXHAUSTED: PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    InspectionKind.GROUP_UNSUPPORTED: PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    InspectionKind.UNSUPPORTED: PREPARE_UNSUPPORTED_ACTIVITY_NAME,
}


@workflow.defn(name=TELEGRAM_USER_WORKFLOW_NAME)
class TelegramUserWorkflow:
    @workflow.init
    def __init__(self, input: UserWorkflowInput) -> None:
        self._user_id = input.user_id
        self._activity_timeout = timedelta(seconds=input.activity_retry_timeout_seconds)
        self._conversation_ttl_seconds = input.conversation_ttl_seconds
        self._pending_update_keys = list(input.pending_update_keys)
        self._recent_update_keys = list(input.recent_update_keys)
        self._active_update_key: str | None = None
        self._continue_as_new_after_updates = input.continue_as_new_after_updates
        self._processed_since_continue = 0
        self._conversation: (
            workflow.ChildWorkflowHandle[TelegramConversationWorkflow, None] | None
        ) = None
        self._conversation_key: str | None = None
        self._conversation_accepting_updates = False
        self._mortal_registered = False

    @workflow.signal(name=TELEGRAM_UPDATE_SIGNAL_NAME)
    def accept_update(self, input: TelegramUpdateSignal) -> None:
        if (
            input.redis_key == self._active_update_key
            or input.redis_key in self._pending_update_keys
            or input.redis_key in self._recent_update_keys
        ):
            return
        self._pending_update_keys.append(input.redis_key)

    @workflow.signal(name=CONVERSATION_FINISHED_SIGNAL_NAME)
    def finish_conversation(self, input: ConversationFinishedSignal) -> None:
        if input.conversation_key == self._conversation_key:
            self._conversation_accepting_updates = False

    @workflow.run
    async def run(self, input: UserWorkflowInput) -> None:
        while True:
            await workflow.wait_condition(lambda: bool(self._pending_update_keys))
            update_key = self._pending_update_keys.pop(0)
            self._active_update_key = update_key
            continue_running = await self._route(update_key)
            self._active_update_key = None
            self._remember(update_key)
            self._processed_since_continue += 1
            if not continue_running:
                return
            await self._continue_as_new_if_needed()

    async def _route(self, update_key: str) -> bool:
        await self._release_finished_conversation()
        if self._conversation is not None and not self._conversation_accepting_updates:
            await self._release_conversation()
        inspected = await self._inspect(update_key)
        if inspected is None:
            await self._cleanup(update_key, f"{update_key}:response")
            return True

        if inspected.kind == InspectionKind.MORTAL_BLOCKED:
            if self._conversation is not None:
                await self._cancel_conversation()
            await self._cleanup(update_key, f"{update_key}:response")
            await self._deactivate_mortal(update_key)
            return False
        if inspected.kind == InspectionKind.MORTAL_UNBLOCKED:
            await self._reset_mortal(update_key)
            await self._cleanup(update_key, f"{update_key}:response")
            return True
        if not await self._ensure_mortal(update_key):
            await self._cleanup(update_key, f"{update_key}:response")
            return True

        if inspected.kind == InspectionKind.NOTIFICATION_SELECTION:
            return await self._respond(inspected)

        if self._conversation is not None and self._conversation_accepting_updates:
            if inspected.kind == InspectionKind.BEGIN:
                quota = await self._prediction_quota(update_key)
                if quota is None:
                    await self._cleanup(update_key, f"{update_key}:response")
                    return True
                if not quota:
                    return await self._respond(self._limit_exhausted(inspected))
                await self._restart_conversation(inspected)
                await self._cleanup(update_key, f"{update_key}:response")
                return True
            if inspected.kind in {
                InspectionKind.ECHO,
                InspectionKind.HELP,
                InspectionKind.ABOUT,
                InspectionKind.NOTIFICATIONS,
            }:
                conversation = await self._release_finished_conversation()
                if conversation is None:
                    return await self._respond(inspected)
                await conversation.signal(
                    CONVERSATION_UPDATE_SIGNAL_NAME,
                    ConversationUpdateSignal(update_key=update_key),
                )
                return True

        if inspected.kind == InspectionKind.BEGIN:
            quota = await self._prediction_quota(update_key)
            if quota is None:
                await self._cleanup(update_key, f"{update_key}:response")
                return True
            if not quota:
                return await self._respond(self._limit_exhausted(inspected))
            await self._start_conversation(inspected)
            await self._cleanup(update_key, f"{update_key}:response")
            return True
        return await self._respond(inspected)

    async def _inspect(self, update_key: str) -> InspectedUpdate | None:
        try:
            return cast(
                InspectedUpdate,
                await workflow.execute_activity(
                    INSPECT_UPDATE_ACTIVITY_NAME,
                    InspectUpdateInput(update_key=update_key, user_id=self._user_id),
                    result_type=InspectedUpdate,
                    schedule_to_close_timeout=self._activity_timeout,
                ),
            )
        except ActivityError:
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Telegram update inspection failed",
                extra=context.event("telegram_update_inspection_failed"),
            )
            return None

    async def _respond(self, inspected: InspectedUpdate) -> bool:
        update_key = inspected.update_key
        response_key = inspected.response_key()
        recipient_available = True
        try:
            prepare_input = PrepareResponseInput(
                update_key=update_key,
                response_key=response_key,
                chat_id=inspected.chat_id,
                user_id=self._user_id,
                callback_query_id=inspected.callback_query_id,
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
        except ActivityError as error:
            if self._recipient_unavailable(error):
                recipient_available = False
                await self._deactivate_mortal(update_key)
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
        return recipient_available

    async def _ensure_mortal(self, update_key: str) -> bool:
        if self._mortal_registered:
            return True
        try:
            await workflow.execute_activity(
                ENSURE_MORTAL_ACTIVITY_NAME,
                MortalActivityInput(mortal_id=self._user_id),
                schedule_to_close_timeout=self._activity_timeout,
            )
        except ActivityError:
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Mortal registration failed",
                extra=context.event("mortal_registration_failed"),
            )
            return False
        self._mortal_registered = True
        return True

    async def _prediction_quota(self, update_key: str) -> bool | None:
        try:
            return cast(
                bool,
                await workflow.execute_activity(
                    CHECK_MORTAL_QUOTA_ACTIVITY_NAME,
                    MortalActivityInput(mortal_id=self._user_id),
                    result_type=bool,
                    schedule_to_close_timeout=self._activity_timeout,
                ),
            )
        except ActivityError:
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Mortal quota check failed",
                extra=context.event("mortal_quota_check_failed"),
            )
            return None

    def _limit_exhausted(self, inspected: InspectedUpdate) -> InspectedUpdate:
        return InspectedUpdate(
            kind=InspectionKind.LIMIT_EXHAUSTED,
            update_key=inspected.update_key,
            chat_id=inspected.chat_id,
            callback_query_id=inspected.callback_query_id,
        )

    async def _deactivate_mortal(self, update_key: str | None) -> None:
        try:
            await workflow.execute_activity(
                DEACTIVATE_MORTAL_ACTIVITY_NAME,
                MortalActivityInput(mortal_id=self._user_id),
                schedule_to_close_timeout=self._activity_timeout,
            )
        except ActivityError:
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Mortal deactivation failed",
                extra=context.event("mortal_deactivation_failed"),
            )
        self._mortal_registered = False

    async def _reset_mortal(self, update_key: str) -> None:
        try:
            await workflow.execute_activity(
                RESET_MORTAL_ACTIVITY_NAME,
                MortalActivityInput(mortal_id=self._user_id),
                schedule_to_close_timeout=self._activity_timeout,
            )
        except ActivityError:
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Mortal reset failed",
                extra=context.event("mortal_reset_failed"),
            )
            self._mortal_registered = False
            return
        self._mortal_registered = True

    async def _start_conversation(self, inspected: InspectedUpdate) -> None:
        conversation_key = f"{inspected.update_key}:conversation"
        child_id = f"{workflow.info().workflow_id}:conversation:{inspected.update_key}"
        self._conversation_key = conversation_key
        self._conversation_accepting_updates = True
        self._conversation = await workflow.start_child_workflow(
            TELEGRAM_CONVERSATION_WORKFLOW_NAME,
            ConversationWorkflowInput(
                conversation_key=conversation_key,
                user_id=self._user_id,
                chat_id=inspected.chat_id,
                inactivity_timeout_seconds=self._conversation_ttl_seconds,
                activity_retry_timeout_seconds=int(self._activity_timeout.total_seconds()),
                owner_workflow_id=workflow.info().workflow_id,
            ),
            id=child_id,
        )

    async def _restart_conversation(self, inspected: InspectedUpdate) -> None:
        await self._cancel_conversation()
        await self._start_conversation(inspected)

    async def _cancel_conversation(self) -> None:
        conversation = cast(
            workflow.ChildWorkflowHandle[TelegramConversationWorkflow, None],
            self._conversation,
        )
        conversation.cancel()
        try:
            await conversation
        except asyncio.CancelledError, ChildWorkflowError:
            pass
        self._conversation = None
        self._conversation_key = None
        self._conversation_accepting_updates = False

    async def _release_finished_conversation(
        self,
    ) -> workflow.ChildWorkflowHandle[TelegramConversationWorkflow, None] | None:
        if self._conversation is not None and self._conversation.done():
            await self._release_conversation()
        return self._conversation

    async def _release_conversation(self) -> None:
        conversation = cast(
            workflow.ChildWorkflowHandle[TelegramConversationWorkflow, None],
            self._conversation,
        )
        try:
            await conversation
        except asyncio.CancelledError, ChildWorkflowError:
            pass
        self._conversation = None
        self._conversation_key = None
        self._conversation_accepting_updates = False

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
        return PREPARE_ACTIVITY_NAMES[kind]

    def _recipient_unavailable(self, error: ActivityError) -> bool:
        return (
            isinstance(error.cause, ApplicationError)
            and error.cause.type == "TelegramRecipientUnavailable"
        )

    def _remember(self, update_key: str) -> None:
        self._recent_update_keys.append(update_key)
        del self._recent_update_keys[:-RECENT_UPDATE_KEYS_LIMIT]

    async def _continue_as_new_if_needed(self) -> None:
        if self._conversation is not None:
            return
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
                conversation_ttl_seconds=self._conversation_ttl_seconds,
                pending_update_keys=tuple(self._pending_update_keys),
                recent_update_keys=tuple(self._recent_update_keys),
                continue_as_new_after_updates=self._continue_as_new_after_updates,
            )
        )
