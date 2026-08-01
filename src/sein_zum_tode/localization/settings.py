import logging

from aiogram.types import Update
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.bot.models import PrepareResponseInput, TelegramResponse
from sein_zum_tode.localization.models import (
    CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME,
    SupportedLocale,
)
from sein_zum_tode.mortals.ports import MortalRepository
from sein_zum_tode.observability import LogContext
from sein_zum_tode.ports.documents import DocumentReader, DocumentWriter


class ConfigureMortalLocalizationActivity:
    def __init__(
        self,
        *,
        updates: DocumentReader[Update],
        responses: DocumentWriter[TelegramResponse],
        mortals: MortalRepository,
        content: BotContent,
        response_ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self._updates = updates
        self._responses = responses
        self._mortals = mortals
        self._content = content
        self._response_ttl_seconds = response_ttl_seconds
        self._logger = logger or logging.getLogger(__name__)

    @activity.defn(name=CONFIGURE_MORTAL_LOCALIZATION_ACTIVITY_NAME)
    async def configure(self, input: PrepareResponseInput) -> None:
        update = await self._updates.load(input.update_key)
        callback = update.callback_query if update is not None else None
        locale = SupportedLocale.from_callback_data(callback.data if callback is not None else None)
        if locale is None or input.user_id is None or locale.value not in self._content.locales:
            raise ApplicationError(
                "Invalid localization selection",
                type="InvalidLocalizationSelection",
                non_retryable=True,
            )
        mortal = await self._mortals.set_locale(input.user_id, locale.value)
        localized = self._content.localized(mortal.locale)
        await self._responses.store(
            input.response_key,
            TelegramResponse(
                chat_id=input.chat_id,
                text=localized.localization.updated,
                callback_query_id=input.callback_query_id,
            ),
            self._response_ttl_seconds,
        )
        self._logger.info(
            "Mortal localization configured",
            extra=LogContext(component="worker", user_id=input.user_id).event(
                "mortal_localization_configured",
                locale=locale.value,
            ),
        )
