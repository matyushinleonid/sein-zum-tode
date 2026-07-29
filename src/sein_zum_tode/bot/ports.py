from typing import Protocol

from aiogram.types import Update

from sein_zum_tode.bot.models import TelegramResponse


class TelegramUpdateReader(Protocol):
    async def load_update(self, key: str) -> Update | None: ...


class TelegramResponseStore(Protocol):
    async def store_response(
        self,
        key: str,
        response: TelegramResponse,
        ttl_seconds: int,
    ) -> None: ...


class TelegramResponseReader(Protocol):
    async def load_response(self, key: str) -> TelegramResponse | None: ...


class TelegramPayloadCleaner(Protocol):
    async def delete(self, keys: tuple[str, ...]) -> None: ...


class TelegramMessageSender(Protocol):
    async def send_text(self, chat_id: int, text: str) -> None: ...
