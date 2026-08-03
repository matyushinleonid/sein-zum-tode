from collections.abc import Sequence

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from sein_zum_tode.bot.models import (
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TELEGRAM_USER_WORKFLOW_NAME,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.ingress.ports import TemporalWorkflowClient


class TemporalClientAdapter:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def start_workflow(
        self,
        workflow: str,
        arg: UserWorkflowInput,
        *,
        id: str,
        task_queue: str,
        id_conflict_policy: WorkflowIDConflictPolicy,
        start_signal: str | None,
        start_signal_args: Sequence[TelegramUpdateSignal],
    ) -> object:
        return await self._client.start_workflow(
            workflow,
            arg,
            id=id,
            task_queue=task_queue,
            id_conflict_policy=id_conflict_policy,
            start_signal=start_signal,
            start_signal_args=start_signal_args,
        )


class TemporalUserWorkflowStarter:
    def __init__(
        self,
        client: TemporalWorkflowClient,
        bot_id: int,
        task_queue: str,
        activity_retry_timeout_seconds: int,
        questionnaire_ttl_seconds: int,
        broadcast_recipient_page_size: int = 100,
    ) -> None:
        self._client = client
        self._bot_id = bot_id
        self._task_queue = task_queue
        self._activity_retry_timeout_seconds = activity_retry_timeout_seconds
        self._questionnaire_ttl_seconds = questionnaire_ttl_seconds
        self._broadcast_recipient_page_size = broadcast_recipient_page_size

    async def signal_with_start(
        self,
        *,
        user_id: int,
        update_key: str,
    ) -> None:
        await self._client.start_workflow(
            TELEGRAM_USER_WORKFLOW_NAME,
            UserWorkflowInput(
                user_id=user_id,
                activity_retry_timeout_seconds=self._activity_retry_timeout_seconds,
                questionnaire_ttl_seconds=self._questionnaire_ttl_seconds,
                broadcast_recipient_page_size=self._broadcast_recipient_page_size,
            ),
            id=f"telegram-user:{self._bot_id}:{user_id}",
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
            start_signal_args=[TelegramUpdateSignal(redis_key=update_key)],
        )
