import asyncio
from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.exceptions import ActivityError, CancelledError

from sein_zum_tode.bot.conversation.models import (
    CONVERSATION_FINISHED_SIGNAL_NAME,
    CONVERSATION_UPDATE_SIGNAL_NAME,
    RECORD_CONVERSATION_ANSWER_ACTIVITY_NAME,
    START_CONVERSATION_ACTIVITY_NAME,
    TELEGRAM_CONVERSATION_WORKFLOW_NAME,
    ConversationFinishedSignal,
    ConversationStarted,
    ConversationTurn,
    ConversationTurnKind,
    ConversationUpdateSignal,
    ConversationWorkflowInput,
    RecordConversationAnswerInput,
    StartConversationInput,
)
from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
    CleanupPayloadsInput,
    DeliverResponseInput,
)
from sein_zum_tode.observability import LogContext


@workflow.defn(name=TELEGRAM_CONVERSATION_WORKFLOW_NAME)
class TelegramConversationWorkflow:
    @workflow.init
    def __init__(self, input: ConversationWorkflowInput) -> None:
        self._conversation_key = input.conversation_key
        self._user_id = input.user_id
        self._chat_id = input.chat_id
        self._owner_workflow_id = input.owner_workflow_id
        self._inactivity_timeout = timedelta(seconds=input.inactivity_timeout_seconds)
        self._activity_timeout = timedelta(seconds=input.activity_retry_timeout_seconds)
        self._pending_update_keys: list[str] = []
        self._recent_update_keys: list[str] = []
        self._active_update_key: str | None = None
        self._privacy_response_key: str | None = None
        self._prepared_response_keys: list[str] = []

    @workflow.signal(name=CONVERSATION_UPDATE_SIGNAL_NAME)
    def accept_update(self, input: ConversationUpdateSignal) -> None:
        if (
            input.update_key == self._active_update_key
            or input.update_key in self._pending_update_keys
            or input.update_key in self._recent_update_keys
        ):
            return
        self._pending_update_keys.append(input.update_key)

    @workflow.run
    async def run(self, input: ConversationWorkflowInput) -> None:
        try:
            started = await self._start()
            if started is None:
                return
            self._privacy_response_key = started.privacy_response_key
            self._prepared_response_keys.extend(started.response_keys)
            delivered = await self._deliver_all(started.response_keys)
            await self._cleanup(started.response_keys)
            self._forget_responses(started.response_keys)
            if not delivered:
                await self._finish(())
                return

            deadline = workflow.time() + self._inactivity_timeout.total_seconds()
            while True:
                remaining = max(0.0, deadline - workflow.time())
                try:
                    await workflow.wait_condition(
                        lambda: bool(self._pending_update_keys),
                        timeout=remaining,
                        timeout_summary="telegram-conversation-inactivity",
                    )
                except TimeoutError:
                    await self._finish(())
                    return

                update_key = self._pending_update_keys.pop(0)
                self._active_update_key = update_key
                turn = await self._record(update_key)
                if turn is None or turn.kind == ConversationTurnKind.EXPIRED:
                    await self._finish((update_key,))
                    return
                if turn.kind == ConversationTurnKind.IGNORED:
                    await self._cleanup((update_key,))
                    self._remember(update_key)
                    self._active_update_key = None
                    continue

                self._prepared_response_keys.extend(turn.response_keys)
                delivered = await self._deliver_all(turn.response_keys, update_key=update_key)
                if turn.completed() or not delivered:
                    await self._finish((update_key, *turn.response_keys))
                    return

                await self._cleanup((update_key, *turn.response_keys))
                self._forget_responses(turn.response_keys)
                self._remember(update_key)
                self._active_update_key = None
                deadline = workflow.time() + self._inactivity_timeout.total_seconds()
        except asyncio.CancelledError:
            await asyncio.shield(self._cleanup_for_restart())
            raise

    async def _start(self) -> ConversationStarted | None:
        try:
            return cast(
                ConversationStarted,
                await workflow.execute_activity(
                    START_CONVERSATION_ACTIVITY_NAME,
                    StartConversationInput(
                        conversation_key=self._conversation_key,
                        user_id=self._user_id,
                        chat_id=self._chat_id,
                    ),
                    result_type=ConversationStarted,
                    schedule_to_close_timeout=self._activity_timeout,
                ),
            )
        except ActivityError as error:
            self._raise_if_cancelled(error)
            self._log_failure("telegram_conversation_start_failed")
            return None

    async def _record(self, update_key: str) -> ConversationTurn | None:
        try:
            return cast(
                ConversationTurn,
                await workflow.execute_activity(
                    RECORD_CONVERSATION_ANSWER_ACTIVITY_NAME,
                    RecordConversationAnswerInput(
                        conversation_key=self._conversation_key,
                        update_key=update_key,
                        user_id=self._user_id,
                    ),
                    result_type=ConversationTurn,
                    schedule_to_close_timeout=self._activity_timeout,
                ),
            )
        except ActivityError as error:
            self._raise_if_cancelled(error)
            self._log_failure(
                "telegram_conversation_answer_failed",
                update_key=update_key,
            )
            return None

    async def _deliver_all(
        self,
        response_keys: tuple[str, ...],
        *,
        update_key: str | None = None,
    ) -> bool:
        for response_key in response_keys:
            try:
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
                self._raise_if_cancelled(error)
                self._log_failure(
                    "telegram_conversation_delivery_failed",
                    update_key=update_key,
                    response_key=response_key,
                )
                return False
        return True

    async def _finish(self, keys: tuple[str, ...]) -> None:
        await self._cleanup((self._conversation_key, *keys))
        self._forget_responses(keys)
        await self._notify_finished()
        privacy_response_key = cast(str, self._privacy_response_key)
        await self._deliver_all((privacy_response_key,), update_key=self._active_update_key)
        await self._cleanup((privacy_response_key,))
        self._privacy_response_key = None

    async def _notify_finished(self) -> None:
        if not self._owner_workflow_id:
            return
        parent = workflow.get_external_workflow_handle(self._owner_workflow_id)
        await parent.signal(
            CONVERSATION_FINISHED_SIGNAL_NAME,
            ConversationFinishedSignal(conversation_key=self._conversation_key),
        )

    async def _cleanup_for_restart(self) -> None:
        keys = [
            self._conversation_key,
            *self._prepared_response_keys,
            *self._pending_update_keys,
        ]
        if self._active_update_key is not None:
            keys.append(self._active_update_key)
        if self._privacy_response_key is not None:
            keys.append(self._privacy_response_key)
        await self._cleanup(tuple(keys))

    async def _cleanup(self, keys: tuple[str, ...]) -> None:
        unique_keys = tuple(dict.fromkeys(keys))
        if not unique_keys:
            return
        try:
            await workflow.execute_activity(
                CLEANUP_PAYLOADS_ACTIVITY_NAME,
                CleanupPayloadsInput(
                    keys=unique_keys,
                    update_key=self._active_update_key,
                    user_id=self._user_id,
                ),
                schedule_to_close_timeout=self._activity_timeout,
            )
        except ActivityError as error:
            self._raise_if_cancelled(error)
            self._log_failure(
                "telegram_conversation_cleanup_failed",
                update_key=self._active_update_key,
            )

    def _forget_responses(self, response_keys: tuple[str, ...]) -> None:
        self._prepared_response_keys = [
            key for key in self._prepared_response_keys if key not in response_keys
        ]

    def _remember(self, update_key: str) -> None:
        self._recent_update_keys.append(update_key)
        del self._recent_update_keys[:-256]

    def _raise_if_cancelled(self, error: ActivityError) -> None:
        if isinstance(error.cause, CancelledError):
            raise asyncio.CancelledError from error

    def _log_failure(
        self,
        event: str,
        *,
        update_key: str | None = None,
        response_key: str | None = None,
    ) -> None:
        workflow.logger.exception(
            "Telegram conversation processing failed",
            extra=LogContext(
                component="worker",
                user_id=self._user_id,
                update_key=update_key,
            ).event(
                event,
                conversation_key=self._conversation_key,
                response_key=response_key,
            ),
        )
