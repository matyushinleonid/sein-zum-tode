from typing import cast

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramDeliveryError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import TelegramButton, TelegramResponse
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

    await sender.send(TelegramResponse(chat_id=170_927, text="Quick wafting zephyrs vex bold Jim"))

    assert bot.events == [
        (
            "send_message",
            (170_927, "Quick wafting zephyrs vex bold Jim", None, None),
        )
    ], "sender changed the destination chat or response text"


async def test_answers_a_callback_and_sends_an_inline_keyboard() -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )
    sender = AiogramTelegramMessageSender(bot)

    await sender.send(
        TelegramResponse(
            chat_id=171_013,
            text="Choose",
            parse_mode="HTML",
            keyboard=(
                (
                    TelegramButton(
                        text="Daily",
                        callback_data="notifications:daily",
                    ),
                ),
            ),
            callback_query_id="callback-171017",
        )
    )

    send_event = bot.events[1]
    send_arguments = cast(tuple[object, ...], send_event[1])
    reply_markup = cast(InlineKeyboardMarkup, send_arguments[3])
    assert (
        bot.events[0],
        send_event[0],
        send_arguments[:3],
        reply_markup.inline_keyboard[0][0].callback_data,
    ) == (
        ("answer_callback_query", "callback-171017"),
        "send_message",
        (171_013, "Choose", "HTML"),
        "notifications:daily",
    ), "callback acknowledgement, HTML mode, or inline keyboard was lost"


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

    with pytest.raises(TelegramRecipientUnavailableError):
        await sender.send(
            TelegramResponse(
                chat_id=172_109,
                text="Waltz, nymph, for quick jigs vex Bud",
            )
        )


async def test_classifies_a_bad_request_as_a_permanent_failure() -> None:
    method = SendMessage(chat_id=172_211, text="Bright vixens jump")
    failure = TelegramBadRequest(method=method, message="bad request 1723")
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=failure,
    )
    sender = AiogramTelegramMessageSender(bot)

    with pytest.raises(PermanentTelegramDeliveryError):
        await sender.send(TelegramResponse(chat_id=172_211, text="Bright vixens jump"))


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
        await sender.send(
            TelegramResponse(
                chat_id=172_337,
                text="Pack my red box with five dozen quality jugs",
            )
        )
