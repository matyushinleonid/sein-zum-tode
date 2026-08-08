import logging

from aiogram.types import Update

from sein_zum_tode.ingress.ports import UpdateUserResolver
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics


class WhitelistedUpdateAdmission:
    def __init__(
        self,
        user_resolver: UpdateUserResolver,
        allowed_user_ids: frozenset[int],
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._user_resolver = user_resolver
        self._allowed_user_ids = allowed_user_ids
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    def admits(self, update: Update) -> bool:
        if not self._allowed_user_ids:
            return True
        user_id = self._user_resolver.resolve(update)
        if user_id in self._allowed_user_ids:
            return True
        self._logger.info(
            "Telegram update rejected by access policy",
            extra=LogContext(component="ingress", user_id=user_id).event(
                "telegram_update_not_allowed",
                update_id=update.update_id,
            ),
        )
        self._metrics.updates(stage="admission", outcome="not_allowed")
        return False
