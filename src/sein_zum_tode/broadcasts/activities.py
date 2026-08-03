import logging
from datetime import timedelta

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramRateLimitedError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.temporal_errors import (
    TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE,
)
from sein_zum_tode.broadcasts.models import (
    DELIVER_SCREAM_ACTIVITY_NAME,
    LIST_SCREAM_RECIPIENTS_ACTIVITY_NAME,
    PREPARE_SCREAM_REPORT_ACTIVITY_NAME,
    DeliverScreamInput,
    ListScreamRecipientsInput,
    PrepareScreamReportInput,
    ScreamRecipients,
)
from sein_zum_tode.broadcasts.ports import MortalAudience, TelegramMessageCopier
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.documents import DocumentWriter
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics


class ListScreamRecipientsActivity:
    def __init__(
        self,
        *,
        mortals: MortalAudience,
        logger: logging.Logger | None = None,
    ) -> None:
        self._mortals = mortals
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=LIST_SCREAM_RECIPIENTS_ACTIVITY_NAME)
    async def list(self, input: ListScreamRecipientsInput) -> ScreamRecipients:
        mortal_ids = await self._mortals.list_ids(
            locale=input.locale,
            after_mortal_id=input.after_mortal_id,
            limit=input.limit,
        )
        self._logger.info(
            "Scream recipients selected",
            extra=LogContext(
                component="worker",
                user_id=input.admin_user_id,
                update_key=input.update_key,
            ).event(
                "scream_recipients_selected",
                locale=input.locale,
                recipient_count=len(mortal_ids),
            ),
        )
        return ScreamRecipients(mortal_ids=mortal_ids)


class DeliverScreamActivity:
    def __init__(
        self,
        *,
        copier: TelegramMessageCopier,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._copier = copier
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=DELIVER_SCREAM_ACTIVITY_NAME)
    async def deliver(self, input: DeliverScreamInput) -> None:
        try:
            await self._copier.copy(input.request, input.recipient_id)
        except TelegramRateLimitedError as error:
            self._metrics.broadcast(outcome="rate_limited", locale=input.request.locale)
            raise ApplicationError(
                f"Telegram rate limited scream for chat {input.recipient_id}",
                type="TelegramRateLimited",
                next_retry_delay=timedelta(seconds=error.retry_after_seconds),
            ) from error
        except TelegramRecipientUnavailableError as error:
            self._metrics.broadcast(outcome="recipient_unavailable", locale=input.request.locale)
            raise ApplicationError(
                f"Telegram recipient {input.recipient_id} is unavailable",
                type=TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE,
                non_retryable=True,
            ) from error
        except PermanentTelegramDeliveryError as error:
            self._metrics.broadcast(outcome="permanent_rejection", locale=input.request.locale)
            raise ApplicationError(
                f"Telegram permanently rejected scream for chat {input.recipient_id}",
                type="PermanentTelegramDeliveryError",
                non_retryable=True,
            ) from error
        self._metrics.broadcast(outcome="delivered", locale=input.request.locale)
        self._logger.info(
            "Scream delivered",
            extra=LogContext(
                component="worker",
                user_id=input.recipient_id,
                update_key=input.update_key,
            ).event(
                "scream_delivered",
                admin_user_id=input.admin_user_id,
                locale=input.request.locale,
            ),
        )


class PrepareScreamReportActivity:
    def __init__(
        self,
        *,
        responses: DocumentWriter[TelegramResponse],
        ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._responses = responses
        self._ttl_seconds = ttl_seconds
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=PREPARE_SCREAM_REPORT_ACTIVITY_NAME)
    async def prepare(self, input: PrepareScreamReportInput) -> None:
        await self._responses.store(
            input.response_key,
            TelegramResponse(chat_id=input.admin_chat_id, text=input.text()),
            self._ttl_seconds,
        )
        self._logger.info(
            "Scream report prepared",
            extra=LogContext(
                component="worker",
                user_id=input.admin_user_id,
                update_key=input.update_key,
            ).event(
                "scream_report_prepared",
                delivered=input.delivered,
                failed=input.failed,
            ),
        )
