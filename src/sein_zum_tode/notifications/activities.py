import logging
from datetime import UTC, datetime
from typing import Protocol

from temporalio import activity

from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.notifications.models import (
    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
)
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.documents import DocumentWriter


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class PrepareMortalNotificationActivity:
    def __init__(
        self,
        *,
        mortals: MortalRepository,
        responses: DocumentWriter[TelegramResponse],
        content: BotContent,
        response_ttl_seconds: int,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._mortals = mortals
        self._responses = responses
        self._content = content
        self._response_ttl_seconds = response_ttl_seconds
        self._clock = clock or SystemClock()
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME)
    async def prepare(
        self,
        input: PrepareMortalNotificationInput,
    ) -> PreparedMortalNotification | None:
        mortal = await self._mortals.get(input.mortal_id)
        if mortal is None or mortal.notification_cron is None:
            return None
        days_left = mortal.days_left(self._clock.now())
        if days_left is None:
            return None
        text = self._content.localized(mortal.locale).notification_text(days_left)
        await self._responses.store(
            input.response_key,
            TelegramResponse(chat_id=mortal.id, text=text),
            self._response_ttl_seconds,
        )
        self._logger.info(
            "Mortal notification prepared",
            extra=LogContext(component="worker", user_id=mortal.id).event(
                "mortal_notification_prepared",
                days_left=days_left,
                response_key=input.response_key,
            ),
        )
        return PreparedMortalNotification(
            response_key=input.response_key,
            days_left=days_left,
        )
