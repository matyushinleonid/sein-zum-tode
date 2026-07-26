import logging

from sein_zum_tode.ingress.models import StoredUpdate


class LoggingUpdateHandoff:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    async def handoff(self, update: StoredUpdate) -> None:
        self._logger.info(
            "Telegram update accepted: update_id=%d redis_key=%s ttl_seconds=%d",
            update.update_id,
            update.key,
            update.ttl_seconds,
        )
