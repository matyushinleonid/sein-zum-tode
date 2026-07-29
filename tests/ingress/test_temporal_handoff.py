from types import SimpleNamespace
from unittest.mock import AsyncMock

from temporalio.common import WorkflowIDConflictPolicy

from sein_zum_tode.bot.models import (
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.ingress.temporal import TemporalUserWorkflowStarter


async def test_starter_uses_signal_with_start() -> None:
    start_workflow = AsyncMock()
    client = SimpleNamespace(start_workflow=start_workflow)
    starter = TemporalUserWorkflowStarter(
        client=client,
        bot_id=42,
        task_queue="telegram",
        activity_retry_timeout_seconds=300,
    )

    await starter.signal_with_start(
        user_id=40,
        update_key="telegram:updates:42:17",
    )

    start_workflow.assert_awaited_once_with(
        TelegramUserWorkflow.run,
        UserWorkflowInput(
            user_id=40,
            activity_retry_timeout_seconds=300,
        ),
        id="telegram-user:42:40",
        task_queue="telegram",
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
        start_signal_args=[TelegramUpdateSignal(redis_key="telegram:updates:42:17")],
    )
