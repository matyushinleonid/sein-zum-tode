import logging

from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.bot.models import PrepareResponseInput, TelegramResponse
from sein_zum_tode.infrastructure.clock import SystemClock
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.models import (
    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
    PREPARE_NOTIFICATION_SAMPLE_ACTIVITY_NAME,
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
    RenderedNotification,
)
from sein_zum_tode.notifications.ports import NotificationPresenter
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.clock import Clock
from sein_zum_tode.ports.documents import DocumentWriter
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics


class PrepareMortalNotificationActivity:
    def __init__(
        self,
        *,
        mortals: MortalRepository,
        responses: DocumentWriter[TelegramResponse],
        presenter: NotificationPresenter,
        response_ttl_seconds: int,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._mortals = mortals
        self._responses = responses
        self._presenter = presenter
        self._response_ttl_seconds = response_ttl_seconds
        self._clock = clock or SystemClock()
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME)
    async def prepare(
        self,
        input: PrepareMortalNotificationInput,
    ) -> PreparedMortalNotification | None:
        mortal = await self._mortals.get(input.mortal_id)
        if (
            mortal is None
            or mortal.notification_cron is None
            or mortal.telegram_unreachable_at is not None
        ):
            self._metrics.notification(
                outcome="skipped_ineligible",
                locale=mortal.locale or "unknown" if mortal is not None else "unknown",
            )
            return None
        days_left = mortal.days_left(self._clock.now())
        if days_left is None:
            self._metrics.notification(
                outcome="skipped_no_prediction",
                locale=mortal.locale or "unknown",
            )
            return None
        rendered = self._presenter.render(
            locale=mortal.locale,
            days_left=days_left,
            seed=input.response_key,
        )
        await self._responses.store(
            input.response_key,
            _response(mortal.id, rendered),
            self._response_ttl_seconds,
        )
        self._metrics.notification(
            outcome="prepared",
            locale=mortal.locale or "unknown",
        )
        self._logger.info(
            "Mortal notification prepared",
            extra=LogContext(component="worker", user_id=mortal.id).event(
                "mortal_notification_prepared",
                response_key=input.response_key,
                notification_variant=rendered.variant_id,
                notification_tier=rendered.tier.value if rendered.tier is not None else "none",
            ),
        )
        return PreparedMortalNotification(
            response_key=input.response_key,
            days_left=days_left,
        )


class PrepareNotificationSampleActivity:
    def __init__(
        self,
        *,
        mortals: MortalRepository,
        responses: DocumentWriter[TelegramResponse],
        presenter: NotificationPresenter,
        content: BotContent,
        response_ttl_seconds: int,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._mortals = mortals
        self._responses = responses
        self._presenter = presenter
        self._content = content
        self._response_ttl_seconds = response_ttl_seconds
        self._clock = clock or SystemClock()
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=PREPARE_NOTIFICATION_SAMPLE_ACTIVITY_NAME)
    async def prepare(self, input: PrepareResponseInput) -> None:
        tier = input.notification_sample
        if tier is None:
            raise ApplicationError(
                "Notification sample tier is missing",
                type="InvalidNotificationSample",
                non_retryable=True,
            )
        mortal = await self._mortals.get(input.user_id) if input.user_id is not None else None
        days_left = mortal.days_left(self._clock.now()) if mortal is not None else None
        if mortal is None or days_left is None:
            locale = mortal.locale if mortal is not None else None
            response = TelegramResponse(
                chat_id=input.chat_id,
                text=self._content.localized(locale).text_unsupported,
            )
            outcome = "sample_no_prediction"
        else:
            rendered = self._presenter.render(
                locale=mortal.locale,
                days_left=days_left,
                seed=input.response_key,
                sample=tier,
            )
            response = _response(input.chat_id, rendered)
            outcome = f"sample_{tier.value}"
        await self._responses.store(
            input.response_key,
            response,
            self._response_ttl_seconds,
        )
        self._metrics.notification(
            outcome=outcome,
            locale=mortal.locale or "unknown" if mortal is not None else "unknown",
        )
        self._logger.info(
            "Notification sample prepared",
            extra=LogContext(
                component="worker",
                user_id=input.user_id,
                update_key=input.update_key,
            ).event(
                "notification_sample_prepared",
                notification_tier=tier.value,
                has_prediction=days_left is not None,
            ),
        )


def _response(chat_id: int, rendered: RenderedNotification) -> TelegramResponse:
    return TelegramResponse(
        chat_id=chat_id,
        text=rendered.text,
        parse_mode=rendered.parse_mode,
        fallback_text=rendered.fallback_text,
        prelude_text=rendered.prelude_text,
        attachment=rendered.attachment,
    )
