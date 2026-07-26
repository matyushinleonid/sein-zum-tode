from collections.abc import Sequence

from aiogram import Bot
from aiogram.enums import UpdateType
from aiogram.exceptions import AiogramError
from aiogram.types import Update

from sein_zum_tode.ingress.errors import UpdateSourceError


class AiogramUpdateSource:
    def __init__(
        self,
        bot: Bot,
        polling_timeout_seconds: int,
        request_timeout_seconds: int,
    ) -> None:
        self._bot = bot
        self._polling_timeout_seconds = polling_timeout_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._allowed_updates = [update_type.value for update_type in UpdateType]

    async def prepare(self) -> None:
        try:
            await self._bot.delete_webhook(drop_pending_updates=False)
        except AiogramError as error:
            raise UpdateSourceError("Failed to remove Telegram webhook") from error

    async def receive(self, offset: int | None) -> Sequence[Update]:
        try:
            return await self._bot.get_updates(
                offset=offset,
                timeout=self._polling_timeout_seconds,
                allowed_updates=self._allowed_updates,
                request_timeout=self._request_timeout_seconds,
            )
        except AiogramError as error:
            raise UpdateSourceError("Failed to receive Telegram updates") from error
