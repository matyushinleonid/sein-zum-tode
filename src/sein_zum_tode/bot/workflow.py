import asyncio
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.exceptions import ActivityError, ChildWorkflowError

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    INSPECT_UPDATE_ACTIVITY_NAME,
    PREPARE_ABOUT_ACTIVITY_NAME,
    PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME,
    PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    PREPARE_HELP_ACTIVITY_NAME,
    PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    PREPARE_LOCALIZATION_ACTIVITY_NAME,
    PREPARE_NOTIFICATIONS_ACTIVITY_NAME,
    PREPARE_PAYLOAD_EXPIRED_ACTIVITY_NAME,
    PREPARE_SCREAM_DENIED_ACTIVITY_NAME,
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TELEGRAM_USER_WORKFLOW_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    InspectUpdateInput,
    PayloadKind,
    PrepareResponseInput,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.bot.temporal_errors import is_telegram_recipient_unavailable
from sein_zum_tode.broadcasts.models import (
    TELEGRAM_SCREAM_WORKFLOW_NAME,
    ScreamRequest,
    ScreamWorkflowInput,
)
from sein_zum_tode.localization.models import (
    CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME,
)
from sein_zum_tode.mortals.activities import (
    CHECK_MORTAL_QUOTA_ACTIVITY_NAME,
    ENSURE_MORTAL_ACTIVITY_NAME,
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
    MortalActivityInput,
    MortalRegistration,
)
from sein_zum_tode.notifications.custom_schedule.models import (
    APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
    GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
    PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME,
    ApplyCustomNotificationScheduleInput,
    GenerateCustomNotificationScheduleInput,
    PrepareCustomNotificationFailureInput,
)
from sein_zum_tode.notifications.models import (
    CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME,
    PREPARE_NOTIFICATION_SAMPLE_ACTIVITY_NAME,
)
from sein_zum_tode.observability import LogContext
from sein_zum_tode.payload_keys import UpdatePayloadKeys
from sein_zum_tode.questionnaire.models import (
    QUESTIONNAIRE_FINISHED_SIGNAL_NAME,
    QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
    TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME,
    QuestionnaireFinishedSignal,
    QuestionnaireUpdateSignal,
    QuestionnaireWorkflowInput,
)
from sein_zum_tode.questionnaire.workflow import TelegramQuestionnaireWorkflow
from sein_zum_tode.unsupported.models import (
    PREPARE_UNSUPPORTED_ACTIVITY_NAME,
    UnsupportedResponsePreparation,
)

RECENT_UPDATE_KEYS_LIMIT = 256
PREPARE_ACTIVITY_NAMES = {
    InspectionKind.HELP: PREPARE_HELP_ACTIVITY_NAME,
    InspectionKind.ABOUT: PREPARE_ABOUT_ACTIVITY_NAME,
    InspectionKind.LOCALIZATION: PREPARE_LOCALIZATION_ACTIVITY_NAME,
    InspectionKind.LOCALIZATION_SELECTION: CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME,
    InspectionKind.NOTIFICATIONS: PREPARE_NOTIFICATIONS_ACTIVITY_NAME,
    InspectionKind.NOTIFICATION_SELECTION: CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME,
    InspectionKind.CUSTOM_NOTIFICATION_SELECTION: PREPARE_CUSTOM_NOTIFICATION_ACTIVITY_NAME,
    InspectionKind.LIMIT_EXHAUSTED: PREPARE_LIMIT_EXHAUSTED_ACTIVITY_NAME,
    InspectionKind.PAYLOAD_EXPIRED: PREPARE_PAYLOAD_EXPIRED_ACTIVITY_NAME,
    InspectionKind.GROUP_UNSUPPORTED: PREPARE_GROUP_UNSUPPORTED_ACTIVITY_NAME,
    InspectionKind.SCREAM_DENIED: PREPARE_SCREAM_DENIED_ACTIVITY_NAME,
    InspectionKind.NOTIFICATION_SAMPLE: PREPARE_NOTIFICATION_SAMPLE_ACTIVITY_NAME,
}
UNSUPPORTED_INSPECTION_KINDS = {
    InspectionKind.TEXT,
    InspectionKind.SCREAM_UNSUPPORTED,
    InspectionKind.UNSUPPORTED,
}


@workflow.defn(name=TELEGRAM_USER_WORKFLOW_NAME)
class TelegramUserWorkflow:
    @workflow.init
    def __init__(self, input: UserWorkflowInput) -> None:
        self._user_id = input.user_id
        self._activity_timeout = timedelta(seconds=input.activity_retry_timeout_seconds)
        self._questionnaire_ttl_seconds = input.questionnaire_ttl_seconds
        self._pending_update_keys = list(input.pending_update_keys)
        self._recent_update_keys = list(input.recent_update_keys)
        self._active_update_key: str | None = None
        self._continue_as_new_after_updates = input.continue_as_new_after_updates
        self._processed_since_continue = 0
        self._questionnaire: (
            workflow.ChildWorkflowHandle[TelegramQuestionnaireWorkflow, None] | None
        ) = None
        self._questionnaire_key: str | None = None
        self._questionnaire_accepting_updates = False
        self._mortal_registered = False
        self._localization_required: bool | None = None
        self._awaiting_custom_notification = input.awaiting_custom_notification
        self._broadcast_recipient_page_size = input.broadcast_recipient_page_size

    @workflow.signal(name=TELEGRAM_UPDATE_SIGNAL_NAME)
    def accept_update(self, input: TelegramUpdateSignal) -> None:
        if (
            input.redis_key == self._active_update_key
            or input.redis_key in self._pending_update_keys
            or input.redis_key in self._recent_update_keys
        ):
            return
        self._pending_update_keys.append(input.redis_key)

    @workflow.signal(name=QUESTIONNAIRE_FINISHED_SIGNAL_NAME)
    def finish_questionnaire(self, input: QuestionnaireFinishedSignal) -> None:
        if input.questionnaire_key == self._questionnaire_key:
            self._questionnaire_accepting_updates = False

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
        payload_keys = UpdatePayloadKeys(update_key)
        await self._release_finished_questionnaire()
        if self._questionnaire is not None and not self._questionnaire_accepting_updates:
            await self._release_questionnaire()
        inspected = await self._inspect(update_key)
        if inspected is None:
            await self._cleanup(update_key, payload_keys.response())
            return True

        if inspected.kind not in {
            InspectionKind.TEXT,
            InspectionKind.PAYLOAD_EXPIRED,
        }:
            self._awaiting_custom_notification = False

        if inspected.kind == InspectionKind.MORTAL_BLOCKED:
            if self._questionnaire is not None:
                await self._cancel_questionnaire()
            await self._cleanup(update_key, payload_keys.response())
            await self._mark_mortal_unreachable(update_key)
            return False
        if inspected.kind == InspectionKind.MORTAL_UNBLOCKED:
            await self._restore_mortal(update_key)
            await self._cleanup(update_key, payload_keys.response())
            return True
        if inspected.kind in {
            InspectionKind.GROUP_UNSUPPORTED,
            InspectionKind.PAYLOAD_EXPIRED,
        }:
            return await self._respond(inspected)
        if not await self._ensure_mortal(update_key):
            await self._cleanup(update_key, payload_keys.response())
            return True

        if inspected.kind in {
            InspectionKind.SCREAM,
            InspectionKind.SCREAM_DENIED,
            InspectionKind.SCREAM_UNSUPPORTED,
        }:
            return await self._route_scream(inspected)

        if self._localization_required and inspected.kind != InspectionKind.LOCALIZATION_SELECTION:
            return await self._respond(self._localization(inspected))

        if inspected.kind in {
            InspectionKind.LOCALIZATION_SELECTION,
            InspectionKind.NOTIFICATION_SELECTION,
        }:
            return await self._respond(inspected)

        if inspected.kind == InspectionKind.CUSTOM_NOTIFICATION_SELECTION:
            self._awaiting_custom_notification = True
            return await self._respond(inspected)

        if self._awaiting_custom_notification and inspected.kind == InspectionKind.TEXT:
            self._awaiting_custom_notification = False
            quota = await self._llm_quota(update_key)
            if quota is None:
                await self._cleanup(update_key, payload_keys.response())
                return True
            if not quota:
                return await self._respond(self._limit_exhausted(inspected))
            return await self._process_custom_notification(inspected)

        if self._questionnaire is not None and self._questionnaire_accepting_updates:
            if inspected.kind == InspectionKind.BEGIN:
                quota = await self._llm_quota(update_key)
                if quota is None:
                    await self._cleanup(update_key, payload_keys.response())
                    return True
                if not quota:
                    return await self._respond(self._limit_exhausted(inspected))
                await self._restart_questionnaire(inspected)
                await self._cleanup(update_key, payload_keys.response())
                return True
            if inspected.kind == InspectionKind.TEXT:
                questionnaire = await self._release_finished_questionnaire()
                if questionnaire is None:
                    return await self._respond(inspected)
                await questionnaire.signal(
                    QUESTIONNAIRE_UPDATE_SIGNAL_NAME,
                    QuestionnaireUpdateSignal(update_key=update_key),
                )
                return True

        if inspected.kind == InspectionKind.BEGIN:
            quota = await self._llm_quota(update_key)
            if quota is None:
                await self._cleanup(update_key, payload_keys.response())
                return True
            if not quota:
                return await self._respond(self._limit_exhausted(inspected))
            await self._start_questionnaire(inspected)
            await self._cleanup(update_key, payload_keys.response())
            return True
        return await self._respond(inspected)

    async def _route_scream(self, inspected: InspectedUpdate) -> bool:
        if inspected.kind != InspectionKind.SCREAM:
            return await self._respond(inspected)
        request = cast(ScreamRequest, inspected.scream_request)
        await workflow.start_child_workflow(
            TELEGRAM_SCREAM_WORKFLOW_NAME,
            ScreamWorkflowInput(
                request=request,
                admin_user_id=self._user_id,
                admin_chat_id=inspected.chat_id,
                update_key=inspected.update_key,
                activity_retry_timeout_seconds=int(self._activity_timeout.total_seconds()),
                recipient_page_size=self._broadcast_recipient_page_size,
            ),
            id=f"telegram-scream:{inspected.update_key}",
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        return True

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
                is_text_message=inspected.kind == InspectionKind.TEXT,
                notification_sample=inspected.notification_sample,
            )
            response_prepared = True
            if inspected.kind in UNSUPPORTED_INSPECTION_KINDS:
                preparation = cast(
                    UnsupportedResponsePreparation,
                    await workflow.execute_activity(
                        PREPARE_UNSUPPORTED_ACTIVITY_NAME,
                        prepare_input,
                        result_type=UnsupportedResponsePreparation,
                        schedule_to_close_timeout=self._activity_timeout,
                    ),
                )
                response_prepared = preparation.response_prepared
            else:
                await workflow.execute_activity(
                    self._prepare_activity_name(inspected.kind),
                    prepare_input,
                    schedule_to_close_timeout=self._activity_timeout,
                )
            if response_prepared:
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
                await self._mark_mortal_unreachable(update_key)
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
        if self._mortal_registered and self._localization_required is False:
            return True
        try:
            registration = cast(
                MortalRegistration,
                await workflow.execute_activity(
                    ENSURE_MORTAL_ACTIVITY_NAME,
                    MortalActivityInput(mortal_id=self._user_id),
                    result_type=MortalRegistration,
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
                "Mortal registration failed",
                extra=context.event("mortal_registration_failed"),
            )
            return False
        self._mortal_registered = True
        self._localization_required = registration.localization_required
        return True

    async def _llm_quota(self, update_key: str) -> bool | None:
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

    async def _process_custom_notification(self, inspected: InspectedUpdate) -> bool:
        update_key = inspected.update_key
        proposal_key = UpdatePayloadKeys(update_key).notification_schedule_proposal()
        response_key = inspected.response_key()
        recipient_available = True
        try:
            try:
                await workflow.execute_activity(
                    GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
                    GenerateCustomNotificationScheduleInput(
                        update_key=update_key,
                        proposal_key=proposal_key,
                        user_id=self._user_id,
                    ),
                    schedule_to_close_timeout=self._activity_timeout,
                )
                await workflow.execute_activity(
                    APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
                    ApplyCustomNotificationScheduleInput(
                        proposal_key=proposal_key,
                        response_key=response_key,
                        user_id=self._user_id,
                        chat_id=inspected.chat_id,
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
                    "Custom notification schedule processing failed",
                    extra=context.event("custom_notification_schedule_processing_failed"),
                )
                await workflow.execute_activity(
                    PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME,
                    PrepareCustomNotificationFailureInput(
                        response_key=response_key,
                        user_id=self._user_id,
                        chat_id=inspected.chat_id,
                    ),
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
                await self._mark_mortal_unreachable(update_key)
            context = LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            )
            workflow.logger.exception(
                "Custom notification schedule response failed",
                extra=context.event("custom_notification_schedule_response_failed"),
            )
        finally:
            await self._cleanup_keys(
                (update_key, proposal_key, response_key),
                update_key=update_key,
                payload_kind=PayloadKind.CUSTOM_SCHEDULE,
            )
        return recipient_available

    def _limit_exhausted(self, inspected: InspectedUpdate) -> InspectedUpdate:
        return InspectedUpdate(
            kind=InspectionKind.LIMIT_EXHAUSTED,
            update_key=inspected.update_key,
            chat_id=inspected.chat_id,
            callback_query_id=inspected.callback_query_id,
        )

    def _localization(self, inspected: InspectedUpdate) -> InspectedUpdate:
        return InspectedUpdate(
            kind=InspectionKind.LOCALIZATION,
            update_key=inspected.update_key,
            chat_id=inspected.chat_id,
            callback_query_id=inspected.callback_query_id,
        )

    async def _mark_mortal_unreachable(self, update_key: str | None) -> None:
        try:
            await workflow.execute_activity(
                MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
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
                "Failed to mark Mortal unreachable",
                extra=context.event("mortal_mark_unreachable_failed"),
            )
        self._mortal_registered = False
        self._localization_required = None

    async def _restore_mortal(self, update_key: str) -> None:
        self._mortal_registered = False
        self._localization_required = None
        await self._ensure_mortal(update_key)

    async def _start_questionnaire(self, inspected: InspectedUpdate) -> None:
        questionnaire_key = f"{inspected.update_key}:questionnaire"
        child_id = f"{workflow.info().workflow_id}:questionnaire:{inspected.update_key}"
        self._questionnaire_key = questionnaire_key
        self._questionnaire_accepting_updates = True
        self._questionnaire = await workflow.start_child_workflow(
            TELEGRAM_QUESTIONNAIRE_WORKFLOW_NAME,
            QuestionnaireWorkflowInput(
                questionnaire_key=questionnaire_key,
                user_id=self._user_id,
                chat_id=inspected.chat_id,
                inactivity_timeout_seconds=self._questionnaire_ttl_seconds,
                activity_retry_timeout_seconds=int(self._activity_timeout.total_seconds()),
                owner_workflow_id=workflow.info().workflow_id,
            ),
            id=child_id,
        )

    async def _restart_questionnaire(self, inspected: InspectedUpdate) -> None:
        await self._cancel_questionnaire()
        await self._start_questionnaire(inspected)

    async def _cancel_questionnaire(self) -> None:
        questionnaire = cast(
            workflow.ChildWorkflowHandle[TelegramQuestionnaireWorkflow, None],
            self._questionnaire,
        )
        questionnaire.cancel()
        try:
            await questionnaire
        except asyncio.CancelledError, ChildWorkflowError:
            pass
        self._questionnaire = None
        self._questionnaire_key = None
        self._questionnaire_accepting_updates = False

    async def _release_finished_questionnaire(
        self,
    ) -> workflow.ChildWorkflowHandle[TelegramQuestionnaireWorkflow, None] | None:
        if self._questionnaire is not None and self._questionnaire.done():
            await self._release_questionnaire()
        return self._questionnaire

    async def _release_questionnaire(self) -> None:
        questionnaire = cast(
            workflow.ChildWorkflowHandle[TelegramQuestionnaireWorkflow, None],
            self._questionnaire,
        )
        try:
            await questionnaire
        except asyncio.CancelledError, ChildWorkflowError:
            pass
        self._questionnaire = None
        self._questionnaire_key = None
        self._questionnaire_accepting_updates = False

    async def _cleanup(self, update_key: str, response_key: str) -> None:
        await self._cleanup_keys(
            (update_key, response_key),
            update_key=update_key,
            response_key=response_key,
        )

    async def _cleanup_keys(
        self,
        keys: tuple[str, ...],
        *,
        update_key: str,
        response_key: str | None = None,
        payload_kind: PayloadKind = PayloadKind.UPDATE,
    ) -> None:
        try:
            await workflow.execute_activity(
                CLEANUP_PAYLOADS_ACTIVITY_NAME,
                CleanupPayloadsInput(
                    keys=keys,
                    update_key=update_key,
                    user_id=self._user_id,
                    payload_kind=payload_kind,
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
        return is_telegram_recipient_unavailable(error)

    def _remember(self, update_key: str) -> None:
        self._recent_update_keys.append(update_key)
        del self._recent_update_keys[:-RECENT_UPDATE_KEYS_LIMIT]

    async def _continue_as_new_if_needed(self) -> None:
        if self._questionnaire is not None:
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
                questionnaire_ttl_seconds=self._questionnaire_ttl_seconds,
                pending_update_keys=tuple(self._pending_update_keys),
                recent_update_keys=tuple(self._recent_update_keys),
                continue_as_new_after_updates=self._continue_as_new_after_updates,
                awaiting_custom_notification=self._awaiting_custom_notification,
                broadcast_recipient_page_size=self._broadcast_recipient_page_size,
            )
        )
