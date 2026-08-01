from aiogram.exceptions import (
    AiogramError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramUnauthorizedError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramDeliveryError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.ports import TelegramSendingClient


class AiogramTelegramMessageSender:
    def __init__(self, bot: TelegramSendingClient) -> None:
        self._bot = bot

    async def send(self, response: TelegramResponse) -> None:
        try:
            if response.callback_query_id is not None:
                await self._bot.answer_callback_query(response.callback_query_id)
            keyboard = (
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=button.text,
                                callback_data=button.callback_data,
                            )
                            for button in row
                        ]
                        for row in response.keyboard
                    ]
                )
                if response.keyboard
                else None
            )
            await self._bot.send_message(
                chat_id=response.chat_id,
                text=response.text,
                parse_mode=response.parse_mode,
                reply_markup=keyboard,
            )
        except TelegramForbiddenError as error:
            raise TelegramRecipientUnavailableError(
                f"Telegram recipient {response.chat_id} is unavailable"
            ) from error
        except (
            TelegramBadRequest,
            TelegramEntityTooLarge,
            TelegramNotFound,
            TelegramUnauthorizedError,
        ) as error:
            raise PermanentTelegramDeliveryError(
                f"Telegram rejected message for chat {response.chat_id}"
            ) from error
        except AiogramError as error:
            raise TelegramDeliveryError(
                f"Failed to send Telegram message to chat {response.chat_id}"
            ) from error
