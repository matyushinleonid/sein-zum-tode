import logging
from hashlib import sha256
from time import monotonic
from zoneinfo import ZoneInfo

from aiogram.types import Update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.infrastructure.clock import SystemClock
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.custom_schedule.models import (
    APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
    GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME,
    PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME,
    ApplyCustomNotificationScheduleInput,
    GenerateCustomNotificationScheduleInput,
    NotificationScheduleRequest,
    PrepareCustomNotificationFailureInput,
    StoredNotificationScheduleProposal,
)
from sein_zum_tode.notifications.custom_schedule.ports import (
    NotificationScheduleInterpreter,
)
from sein_zum_tode.notifications.custom_schedule.validation import (
    InvalidNotificationScheduleError,
    NotificationScheduleTooFrequentError,
    NotificationScheduleValidator,
)
from sein_zum_tode.notifications.ports import MortalSchedule
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.clock import Clock
from sein_zum_tode.ports.documents import DocumentReader, DocumentStore, DocumentWriter
from sein_zum_tode.ports.metrics import ApplicationMetrics, NoopApplicationMetrics


class GenerateCustomNotificationScheduleActivity:
    def __init__(
        self,
        *,
        interpreter: NotificationScheduleInterpreter,
        proposals: DocumentStore[StoredNotificationScheduleProposal],
        updates: DocumentReader[Update],
        mortals: MortalRepository,
        default_locale: str,
        ttl_seconds: int,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._interpreter = interpreter
        self._proposals = proposals
        self._updates = updates
        self._mortals = mortals
        self._default_locale = default_locale
        self._ttl_seconds = ttl_seconds
        self._clock = clock or SystemClock()
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=GENERATE_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME)
    async def generate(self, input: GenerateCustomNotificationScheduleInput) -> None:
        stored = await self._proposals.load(input.proposal_key)
        if stored is None:
            update = await self._updates.load(input.update_key)
            mortal = await self._mortals.get(input.user_id)
            message = update.message if update is not None else None
            if mortal is None or message is None or message.text is None:
                raise ApplicationError(
                    "Custom notification schedule input expired",
                    type="CustomNotificationScheduleInputNotFound",
                    non_retryable=True,
                )
            now = self._clock.now()
            request = NotificationScheduleRequest(
                locale=mortal.locale or self._default_locale,
                current_cron=mortal.notification_cron,
                current_timezone=mortal.timezone,
                current_local_datetime=now.astimezone(ZoneInfo(mortal.timezone)),
                user_request=message.text,
            )
            started = monotonic()
            try:
                proposal = await self._interpreter.interpret(request)
            except Exception:
                self._metrics.llm_request(
                    use_case="notification_schedule",
                    provider=self._interpreter.provider_name,
                    outcome="failed",
                    elapsed_seconds=monotonic() - started,
                )
                raise
            self._metrics.llm_request(
                use_case="notification_schedule",
                provider=self._interpreter.provider_name,
                outcome="success",
                elapsed_seconds=monotonic() - started,
            )
            stored = StoredNotificationScheduleProposal(
                request_id=sha256(input.proposal_key.encode()).hexdigest(),
                provider=self._interpreter.provider_name,
                consumes_quota=self._interpreter.consumes_quota,
                proposal=proposal,
            )
            await self._proposals.store(
                input.proposal_key,
                stored,
                self._ttl_seconds,
            )
        if stored.consumes_quota:
            await self._mortals.consume_llm_request(input.user_id, stored.request_id)
        self._logger.info(
            "Custom notification schedule generated",
            extra=LogContext(component="worker", user_id=input.user_id).event(
                "custom_notification_schedule_generated",
                provider=stored.provider,
                understood=stored.proposal.understood,
            ),
        )


class ApplyCustomNotificationScheduleActivity:
    def __init__(
        self,
        *,
        proposals: DocumentReader[StoredNotificationScheduleProposal],
        responses: DocumentWriter[TelegramResponse],
        mortals: MortalRepository,
        schedules: MortalSchedule,
        validator: NotificationScheduleValidator,
        content: BotContent,
        response_ttl_seconds: int,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
        metrics: ApplicationMetrics | None = None,
    ) -> None:
        self._proposals = proposals
        self._responses = responses
        self._mortals = mortals
        self._schedules = schedules
        self._validator = validator
        self._content = content
        self._response_ttl_seconds = response_ttl_seconds
        self._clock = clock or SystemClock()
        self._logger = logger or logging.getLogger(__name__)
        self._metrics = metrics or NoopApplicationMetrics()

    @activity.defn(name=APPLY_CUSTOM_NOTIFICATION_SCHEDULE_ACTIVITY_NAME)
    async def apply(self, input: ApplyCustomNotificationScheduleInput) -> None:
        stored = await self._proposals.load(input.proposal_key)
        mortal = await self._mortals.get(input.user_id)
        if stored is None or mortal is None:
            raise ApplicationError(
                "Custom notification schedule proposal expired",
                type="CustomNotificationScheduleProposalNotFound",
                non_retryable=True,
            )
        localized = self._content.localized(mortal.locale)
        proposal = stored.proposal
        text = proposal.explanation
        applied = False
        outcome = "not_understood"
        if proposal.understood:
            settings = proposal.settings()
            try:
                self._validator.validate(settings, now=self._clock.now())
            except NotificationScheduleTooFrequentError:
                text = localized.notification_settings.custom_too_frequent
                outcome = "too_frequent"
            except InvalidNotificationScheduleError:
                text = localized.notification_settings.custom_invalid
                outcome = "invalid"
            else:
                mortal = await self._mortals.set_notification_settings(
                    input.user_id,
                    cron=settings.cron,
                    timezone=settings.timezone,
                )
                await self._schedules.ensure(mortal)
                applied = True
                outcome = "applied"
        await self._responses.store(
            input.response_key,
            TelegramResponse(chat_id=input.chat_id, text=text),
            self._response_ttl_seconds,
        )
        self._metrics.notification_schedule(
            kind="custom",
            outcome=outcome,
            locale=mortal.locale or "unknown",
        )
        self._logger.info(
            "Custom notification schedule applied",
            extra=LogContext(component="worker", user_id=input.user_id).event(
                "custom_notification_schedule_applied",
                provider=stored.provider,
                applied=applied,
            ),
        )


class PrepareCustomNotificationFailureActivity:
    def __init__(
        self,
        *,
        mortals: MortalRepository,
        responses: DocumentWriter[TelegramResponse],
        content: BotContent,
        response_ttl_seconds: int,
    ) -> None:
        self._mortals = mortals
        self._responses = responses
        self._content = content
        self._response_ttl_seconds = response_ttl_seconds

    @activity.defn(name=PREPARE_CUSTOM_NOTIFICATION_FAILURE_ACTIVITY_NAME)
    async def prepare(self, input: PrepareCustomNotificationFailureInput) -> None:
        mortal = await self._mortals.get(input.user_id)
        locale = mortal.locale if mortal is not None else self._content.default_locale
        await self._responses.store(
            input.response_key,
            TelegramResponse(
                chat_id=input.chat_id,
                text=self._content.localized(locale).notification_settings.custom_failed,
            ),
            self._response_ttl_seconds,
        )
