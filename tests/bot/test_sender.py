from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendMessage

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramDeliveryError,
)
from sein_zum_tode.bot.sender import AiogramTelegramMessageSender


async def test_sender_sends_plain_text() -> None:
    bot = Mock(spec=Bot)
    bot.send_message = AsyncMock()
    sender = AiogramTelegramMessageSender(bot)

    await sender.send_text(30, "<sensitive>")

    bot.send_message.assert_awaited_once_with(chat_id=30, text="<sensitive>")


async def test_sender_maps_permanent_telegram_error() -> None:
    bot = Mock(spec=Bot)
    bot.send_message = AsyncMock(
        side_effect=TelegramBadRequest(
            method=SendMessage(chat_id=30, text="response"),
            message="bad request",
        )
    )
    sender = AiogramTelegramMessageSender(bot)

    with pytest.raises(PermanentTelegramDeliveryError, match="chat 30"):
        await sender.send_text(30, "response")


async def test_sender_maps_transient_telegram_error() -> None:
    bot = Mock(spec=Bot)
    bot.send_message = AsyncMock(
        side_effect=TelegramNetworkError(
            method=SendMessage(chat_id=30, text="response"),
            message="network",
        )
    )
    sender = AiogramTelegramMessageSender(bot)

    with pytest.raises(TelegramDeliveryError, match="chat 30"):
        await sender.send_text(30, "response")
