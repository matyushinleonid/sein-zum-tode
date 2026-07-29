from collections.abc import Callable
from unittest.mock import create_autospec

import pytest
from aiogram import Bot
from aiogram.enums import UpdateType
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetUpdates
from aiogram.types import Update

from sein_zum_tode.ingress.errors import UpdateSourceError
from sein_zum_tode.ingress.source import AiogramUpdateSource


async def test_prepare_preserves_pending_updates() -> None:
    bot = create_autospec(Bot, instance=True)
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=30,
        request_timeout_seconds=40,
    )

    await source.prepare()

    bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)


async def test_receive_requests_every_known_update_type(
    make_update: Callable[[int, str], Update],
) -> None:
    update = make_update(7, "sensitive")
    bot = create_autospec(Bot, instance=True)
    bot.get_updates.return_value = [update]
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=31,
        request_timeout_seconds=45,
    )

    received = await source.receive(6)

    assert received == [update]
    bot.get_updates.assert_awaited_once_with(
        offset=6,
        timeout=31,
        allowed_updates=[update_type.value for update_type in UpdateType],
        request_timeout=45,
    )


async def test_prepare_wraps_aiogram_error() -> None:
    bot = create_autospec(Bot, instance=True)
    bot.delete_webhook.side_effect = TelegramNetworkError(
        method=GetUpdates(),
        message="network",
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=30,
        request_timeout_seconds=40,
    )

    with pytest.raises(UpdateSourceError, match="remove Telegram webhook"):
        await source.prepare()


async def test_receive_wraps_aiogram_error() -> None:
    bot = create_autospec(Bot, instance=True)
    bot.get_updates.side_effect = TelegramNetworkError(
        method=GetUpdates(),
        message="network",
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=30,
        request_timeout_seconds=40,
    )

    with pytest.raises(UpdateSourceError, match="receive Telegram updates"):
        await source.receive(None)
