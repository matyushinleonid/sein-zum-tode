from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from sein_zum_tode.bot.models import (
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.ingress.ports import UserWorkflowStarter


class TemporalUserWorkflowStarter(UserWorkflowStarter):
    def __init__(
        self,
        client: Client,
        bot_id: int,
        task_queue: str,
        activity_retry_timeout_seconds: int,
    ) -> None:
        self._client = client
        self._bot_id = bot_id
        self._task_queue = task_queue
        self._activity_retry_timeout_seconds = activity_retry_timeout_seconds

    async def signal_with_start(
        self,
        *,
        user_id: int,
        update_key: str,
    ) -> None:
        await self._client.start_workflow(
            TelegramUserWorkflow.run,
            UserWorkflowInput(
                user_id=user_id,
                activity_retry_timeout_seconds=self._activity_retry_timeout_seconds,
            ),
            id=f"telegram-user:{self._bot_id}:{user_id}",
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
            start_signal_args=[TelegramUpdateSignal(redis_key=update_key)],
        )
