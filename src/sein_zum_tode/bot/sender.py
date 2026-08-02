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
from sein_zum_tode.broadcasts.models import ScreamRequest


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
            await self._send_with_fallback(response, keyboard)
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

    async def _send_with_fallback(
        self,
        response: TelegramResponse,
        keyboard: InlineKeyboardMarkup | None,
    ) -> None:
        try:
            await self._bot.send_message(
                chat_id=response.chat_id,
                text=response.text,
                parse_mode=response.parse_mode,
                reply_markup=keyboard,
            )
        except TelegramBadRequest:
            if response.fallback_text is None:
                raise
            await self._bot.send_message(
                chat_id=response.chat_id,
                text=response.fallback_text,
                parse_mode=None,
                reply_markup=keyboard,
            )

    async def copy(self, request: ScreamRequest, recipient_id: int) -> None:
        try:
            await self._bot.copy_message(
                chat_id=recipient_id,
                from_chat_id=request.source_chat_id,
                message_id=request.source_message_id,
            )
        except TelegramForbiddenError as error:
            raise TelegramRecipientUnavailableError(
                f"Telegram recipient {recipient_id} is unavailable"
            ) from error
        except (
            TelegramBadRequest,
            TelegramEntityTooLarge,
            TelegramNotFound,
            TelegramUnauthorizedError,
        ) as error:
            raise PermanentTelegramDeliveryError(
                f"Telegram rejected copied message for chat {recipient_id}"
            ) from error
        except AiogramError as error:
            raise TelegramDeliveryError(
                f"Failed to copy Telegram message to chat {recipient_id}"
            ) from error
