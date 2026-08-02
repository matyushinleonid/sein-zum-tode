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
from sein_zum_tode.bot.models import TelegramAttachmentKind, TelegramResponse
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
            if response.prelude_text is not None:
                await self._bot.send_message(
                    chat_id=response.chat_id,
                    text=response.prelude_text,
                    parse_mode=None,
                    reply_markup=None,
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
            await self._send_main(response, keyboard, fallback=False)
        except TelegramBadRequest:
            if response.fallback_text is None:
                raise
            await self._send_main(response, keyboard, fallback=True)

    async def _send_main(
        self,
        response: TelegramResponse,
        keyboard: InlineKeyboardMarkup | None,
        *,
        fallback: bool,
    ) -> None:
        text = response.fallback_text if fallback else response.text
        parse_mode = None if fallback else response.parse_mode
        assert text is not None
        attachment = response.attachment
        if attachment is None:
            await self._bot.send_message(
                chat_id=response.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=keyboard,
            )
            return
        if attachment.kind == TelegramAttachmentKind.AUDIO:
            await self._bot.send_audio(
                chat_id=response.chat_id,
                audio=attachment.url,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=keyboard,
            )
        elif attachment.kind == TelegramAttachmentKind.PHOTO:
            await self._bot.send_photo(
                chat_id=response.chat_id,
                photo=attachment.url,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=keyboard,
            )
        elif attachment.kind == TelegramAttachmentKind.VIDEO:
            await self._bot.send_video(
                chat_id=response.chat_id,
                video=attachment.url,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=keyboard,
            )
        else:
            await self._bot.send_document(
                chat_id=response.chat_id,
                document=attachment.url,
                caption=text,
                parse_mode=parse_mode,
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
