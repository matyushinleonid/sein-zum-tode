import logging
from unittest.mock import Mock

from sein_zum_tode.ingress.handoff import LoggingUpdateHandoff
from sein_zum_tode.ingress.models import StoredUpdate


async def test_logging_handoff_logs_only_reference() -> None:
    logger = Mock(spec=logging.Logger)
    handoff = LoggingUpdateHandoff(logger)
    update = StoredUpdate(
        update_id=17,
        key="telegram:updates:42:17",
        ttl_seconds=600,
    )

    await handoff.handoff(update)

    logger.info.assert_called_once_with(
        "Telegram update accepted: update_id=%d redis_key=%s ttl_seconds=%d",
        17,
        "telegram:updates:42:17",
        600,
    )
