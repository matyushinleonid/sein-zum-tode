import logging

from temporalio.exceptions import TemporalError

from sein_zum_tode.ingress.errors import UpdateHandoffError
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.ports import UpdateHandoff, UserWorkflowStarter
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics


class LoggingUpdateHandoff:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

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
        self._metrics.updates(stage="handoff", outcome="success")


class WhitelistedUpdateHandoff:
    def __init__(
        self,
        delegate: UpdateHandoff,
        allowed_user_ids: frozenset[int],
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._delegate = delegate
        self._allowed_user_ids = allowed_user_ids
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    async def handoff(self, update: StoredUpdate) -> None:
        if (
            not self._allowed_user_ids
            or update.user_id is None
            or update.user_id in self._allowed_user_ids
        ):
            await self._delegate.handoff(update)
            return
        self._logger.info(
            "Telegram update rejected by access policy",
            extra=LogContext(
                component="ingress",
                user_id=update.user_id,
                update_key=update.key,
            ).event(
                "telegram_update_not_allowed",
                update_id=update.update_id,
            ),
        )
        self._metrics.updates(stage="handoff", outcome="not_allowed")


class TemporalUpdateHandoff:
    def __init__(
        self,
        workflow_starter: UserWorkflowStarter,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._workflow_starter = workflow_starter
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    async def handoff(self, update: StoredUpdate) -> None:
        context = LogContext(
            component="ingress",
            user_id=update.user_id,
            update_key=update.key,
        )
        if update.user_id is None:
            self._metrics.updates(stage="handoff", outcome="unroutable")
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
            self._metrics.updates(stage="handoff", outcome="failed")
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
        self._metrics.updates(stage="handoff", outcome="success")
