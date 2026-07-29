import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramDeliveryError,
)
from sein_zum_tode.bot.sender import AiogramTelegramMessageSender
from tests.support import TelegramBotDouble

pytestmark = pytest.mark.fast


async def test_sends_plain_text_through_the_telegram_bot() -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )
    sender = AiogramTelegramMessageSender(bot)

    await sender.send_text(170_927, "Quick wafting zephyrs vex bold Jim")

    assert bot.events == [("send_message", (170_927, "Quick wafting zephyrs vex bold Jim"))], (
        "sender changed the destination chat or response text"
    )


async def test_classifies_a_rejected_chat_as_a_permanent_failure() -> None:
    method = SendMessage(chat_id=172_109, text="Waltz, nymph, for quick jigs vex Bud")
    failure = TelegramForbiddenError(method=method, message="forbidden galaxy 1721")
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=failure,
    )
    sender = AiogramTelegramMessageSender(bot)

    with pytest.raises(PermanentTelegramDeliveryError):
        await sender.send_text(172_109, "Waltz, nymph, for quick jigs vex Bud")


async def test_classifies_a_network_problem_as_a_retryable_failure() -> None:
    method = SendMessage(chat_id=172_337, text="Pack my red box with five dozen quality jugs")
    failure = TelegramNetworkError(method=method, message="network aurora 1723")
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=failure,
    )
    sender = AiogramTelegramMessageSender(bot)

    with pytest.raises(TelegramDeliveryError):
        await sender.send_text(172_337, "Pack my red box with five dozen quality jugs")
