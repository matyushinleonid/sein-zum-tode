from aiogram import Bot
from aiogram.exceptions import (
    AiogramError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramUnauthorizedError,
)

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramDeliveryError,
)
from sein_zum_tode.bot.ports import TelegramMessageSender


class AiogramTelegramMessageSender(TelegramMessageSender):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(self, chat_id: int, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
        except (
            TelegramBadRequest,
            TelegramEntityTooLarge,
            TelegramForbiddenError,
            TelegramNotFound,
            TelegramUnauthorizedError,
        ) as error:
            raise PermanentTelegramDeliveryError(
                f"Telegram rejected message for chat {chat_id}"
            ) from error
        except AiogramError as error:
            raise TelegramDeliveryError(
                f"Failed to send Telegram message to chat {chat_id}"
            ) from error
