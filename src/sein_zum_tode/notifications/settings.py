import logging

from aiogram.types import Update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.bot.models import PrepareResponseInput, TelegramResponse
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.custom_schedule.config import NotificationPresets
from sein_zum_tode.notifications.models import (
    CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME,
    NotificationFrequency,
)
from sein_zum_tode.notifications.ports import MortalSchedule
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.documents import DocumentReader, DocumentWriter


class ConfigureMortalNotificationsActivity:
    def __init__(
        self,
        *,
        updates: DocumentReader[Update],
        responses: DocumentWriter[TelegramResponse],
        mortals: MortalRepository,
        schedules: MortalSchedule,
        content: BotContent,
        presets: NotificationPresets,
        response_ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._updates = updates
        self._responses = responses
        self._mortals = mortals
        self._schedules = schedules
        self._content = content
        self._presets = presets
        self._response_ttl_seconds = response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=CONFIGURE_MORTAL_NOTIFICATIONS_ACTIVITY_NAME)
    async def configure(self, input: PrepareResponseInput) -> None:
        update = await self._updates.load(input.update_key)
        callback = update.callback_query if update is not None else None
        frequency = NotificationFrequency.from_callback_data(
            callback.data if callback is not None else None
        )
        if frequency is None or input.user_id is None:
            raise ApplicationError(
                "Invalid notification selection",
                type="InvalidNotificationSelection",
                non_retryable=True,
            )
        mortal = await self._mortals.set_notification_cron(
            input.user_id,
            self._presets.cron(frequency),
        )
        await self._schedules.ensure(mortal)
        localized = self._content.localized(mortal.locale)
        label = {
            NotificationFrequency.DAILY: localized.notification_settings.daily,
            NotificationFrequency.WEEKLY: localized.notification_settings.weekly,
            NotificationFrequency.MONTHLY: localized.notification_settings.monthly,
            NotificationFrequency.NEVER: localized.notification_settings.never,
        }[frequency]
        await self._responses.store(
            input.response_key,
            TelegramResponse(
                chat_id=input.chat_id,
                text=localized.notification_settings.updated_text(label),
                callback_query_id=input.callback_query_id,
            ),
            self._response_ttl_seconds,
        )
        self._logger.info(
            "Mortal notification frequency configured",
            extra=LogContext(component="worker", user_id=input.user_id).event(
                "mortal_notification_frequency_configured",
                frequency=frequency.value,
                notification_cron=self._presets.cron(frequency),
            ),
        )
