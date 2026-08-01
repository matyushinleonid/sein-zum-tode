from typing import Protocol

from aiogram.types import InlineKeyboardMarkup

from sein_zum_tode.bot.models import TelegramResponse


class EphemeralPayloadCleaner(Protocol):
    async def delete(self, keys: tuple[str, ...]) -> None: ...


class TelegramMessageSender(Protocol):
    async def send(self, response: TelegramResponse) -> None: ...


class TelegramSendingClient(Protocol):
    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...

    async def answer_callback_query(self, callback_query_id: str) -> object: ...
