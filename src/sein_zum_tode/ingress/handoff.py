import logging

from temporalio.exceptions import TemporalError

from sein_zum_tode.ingress.errors import UpdateHandoffError
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.ports import UserWorkflowStarter
from sein_zum_tode.observability import LogContext


class LoggingUpdateHandoff:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    async def handoff(self, update: StoredUpdate) -> None:
        context = LogContext(
            component="ingress",
            user_id=update.user_id,
            update_key=update.key,
        )
        self._logger.info(
            "Telegram update accepted",
            extra=context.event(
                "telegram_update_logged",
                update_id=update.update_id,
                ttl_seconds=update.ttl_seconds,
            ),
        )


class TemporalUpdateHandoff:
    def __init__(
        self,
        workflow_starter: UserWorkflowStarter,
        logger: logging.Logger | None = None,
    ) -> None:
        self._workflow_starter = workflow_starter
        self._logger = logger or logging.getLogger(__name__)

    async def handoff(self, update: StoredUpdate) -> None:
        context = LogContext(
            component="ingress",
            user_id=update.user_id,
            update_key=update.key,
        )
        if update.user_id is None:
            self._logger.warning(
                "Telegram update has no user route",
                extra=context.event(
                    "telegram_update_unroutable",
                    update_id=update.update_id,
                ),
            )
            return
        try:
            await self._workflow_starter.signal_with_start(
                user_id=update.user_id,
                update_key=update.key,
            )
        except TemporalError as error:
            raise UpdateHandoffError(
                f"Failed to hand off Telegram update {update.update_id} to Temporal"
            ) from error
        self._logger.info(
            "Telegram update handed off",
            extra=context.event(
                "telegram_update_handed_off",
                update_id=update.update_id,
            ),
        )
