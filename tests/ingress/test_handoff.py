import logging
from unittest.mock import Mock, create_autospec

import pytest
from temporalio.exceptions import TemporalError

from sein_zum_tode.ingress.errors import UpdateHandoffError
from sein_zum_tode.ingress.handoff import LoggingUpdateHandoff, TemporalUpdateHandoff
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.ports import UserWorkflowStarter


async def test_logging_handoff_logs_only_reference() -> None:
    logger = Mock(spec=logging.Logger)
    handoff = LoggingUpdateHandoff(logger)
    update = StoredUpdate(
        update_id=17,
        key="telegram:updates:42:17",
        ttl_seconds=600,
        user_id=40,
    )

    await handoff.handoff(update)

    logger.info.assert_called_once_with(
        "Telegram update accepted",
        extra={
            "event": "telegram_update_logged",
            "component": "ingress",
            "user_id": 40,
            "update_id": 17,
            "update_key": "telegram:updates:42:17",
            "ttl_seconds": 600,
        },
    )


async def test_temporal_handoff_signals_user_workflow() -> None:
    starter = create_autospec(UserWorkflowStarter, instance=True)
    logger = Mock(spec=logging.Logger)
    handoff = TemporalUpdateHandoff(starter, logger)

    await handoff.handoff(StoredUpdate(17, "telegram:updates:42:17", 600, user_id=40))

    starter.signal_with_start.assert_awaited_once_with(
        user_id=40,
        update_key="telegram:updates:42:17",
    )
    message = logger.info.call_args.args[0]
    fields = logger.info.call_args.kwargs["extra"]
    assert message == "Telegram update handed off"
    assert fields["event"] == "telegram_update_handed_off"
    assert fields["component"] == "ingress"
    assert fields["user_id"] == 40
    assert fields["update_id"] == 17
    assert fields["update_key"] == "telegram:updates:42:17"
    assert isinstance(fields["duration_ms"], float)


async def test_temporal_handoff_accepts_update_without_user_route() -> None:
    starter = create_autospec(UserWorkflowStarter, instance=True)
    logger = Mock(spec=logging.Logger)
    handoff = TemporalUpdateHandoff(starter, logger)
    update = StoredUpdate(17, "telegram:updates:42:17", 600, user_id=None)

    await handoff.handoff(update)

    starter.signal_with_start.assert_not_awaited()
    logger.warning.assert_called_once_with(
        "Telegram update has no user route",
        extra={
            "event": "telegram_update_unroutable",
            "component": "ingress",
            "user_id": None,
            "update_id": 17,
            "update_key": "telegram:updates:42:17",
        },
    )


async def test_temporal_handoff_wraps_temporal_error() -> None:
    starter = create_autospec(UserWorkflowStarter, instance=True)
    starter.signal_with_start.side_effect = TemporalError("unavailable")
    handoff = TemporalUpdateHandoff(starter)

    with pytest.raises(UpdateHandoffError, match="Telegram update 17"):
        await handoff.handoff(StoredUpdate(17, "telegram:updates:42:17", 600, user_id=40))
