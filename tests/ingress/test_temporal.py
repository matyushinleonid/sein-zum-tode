from typing import cast

import pytest
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from sein_zum_tode.bot.models import (
    TELEGRAM_UPDATE_SIGNAL_NAME,
    TELEGRAM_USER_WORKFLOW_NAME,
    TelegramUpdateSignal,
    UserWorkflowInput,
)
from sein_zum_tode.ingress.temporal import TemporalClientAdapter, TemporalUserWorkflowStarter
from tests.support import TemporalClientDouble

pytestmark = pytest.mark.fast


async def test_adapts_the_temporal_sdk_client_to_the_ingress_port() -> None:
    client = TemporalClientDouble(None)
    adapter = TemporalClientAdapter(cast(Client, cast(object, client)))
    input = UserWorkflowInput(
        user_id=108_887,
        activity_retry_timeout_seconds=1087,
        questionnaire_ttl_seconds=1091,
    )
    signal = TelegramUpdateSignal(redis_key="telegram:aurora:1093")

    await adapter.start_workflow(
        TELEGRAM_USER_WORKFLOW_NAME,
        input,
        id="telegram-user:1081:108887",
        task_queue="telegram-aurora-1097",
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        start_signal=TELEGRAM_UPDATE_SIGNAL_NAME,
        start_signal_args=[signal],
    )

    assert client.events == [
        (
            TELEGRAM_USER_WORKFLOW_NAME,
            input,
            {
                "id": "telegram-user:1081:108887",
                "task_queue": "telegram-aurora-1097",
                "id_conflict_policy": WorkflowIDConflictPolicy.USE_EXISTING,
                "start_signal": TELEGRAM_UPDATE_SIGNAL_NAME,
                "start_signal_args": [signal],
            },
        )
    ], "Temporal SDK adapter lost signal-with-start arguments"


async def test_signals_or_starts_the_workflow_owned_by_one_user() -> None:
    client = TemporalClientDouble(None)
    starter = TemporalUserWorkflowStarter(
        client=client,
        bot_id=1091,
        task_queue="telegram-aurora-1093",
        activity_retry_timeout_seconds=1097,
        questionnaire_ttl_seconds=1109,
    )

    await starter.signal_with_start(user_id=109_891, update_key="telegram:aurora:1103")

    assert client.events == [
        (
            TELEGRAM_USER_WORKFLOW_NAME,
            UserWorkflowInput(
                user_id=109_891,
                activity_retry_timeout_seconds=1097,
                questionnaire_ttl_seconds=1109,
            ),
            {
                "id": "telegram-user:1091:109891",
                "task_queue": "telegram-aurora-1093",
                "id_conflict_policy": WorkflowIDConflictPolicy.USE_EXISTING,
                "start_signal": TELEGRAM_UPDATE_SIGNAL_NAME,
                "start_signal_args": [TelegramUpdateSignal(redis_key="telegram:aurora:1103")],
            },
        )
    ], "starter did not preserve workflow identity or signal-with-start options"
