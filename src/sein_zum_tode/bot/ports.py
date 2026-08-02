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

    async def send_audio(
        self,
        *,
        chat_id: int,
        audio: str,
        caption: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: str,
        caption: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...

    async def send_video(
        self,
        *,
        chat_id: int,
        video: str,
        caption: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...

    async def send_document(
        self,
        *,
        chat_id: int,
        document: str,
        caption: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...

    async def answer_callback_query(self, callback_query_id: str) -> object: ...

    async def copy_message(
        self,
        *,
        chat_id: int,
        from_chat_id: int,
        message_id: int,
    ) -> object: ...
