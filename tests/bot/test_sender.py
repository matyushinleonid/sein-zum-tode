from typing import cast

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.methods import CopyMessage, SendMessage
from aiogram.types import InlineKeyboardMarkup

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramDeliveryError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import TelegramButton, TelegramResponse
from sein_zum_tode.bot.sender import AiogramTelegramMessageSender
from sein_zum_tode.broadcasts.models import ScreamRequest
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


async def test_copies_a_replied_message_without_rebuilding_its_media() -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )

    await AiogramTelegramMessageSender(bot).copy(
        ScreamRequest(
            locale="ru",
            source_chat_id=172_411,
            source_message_id=172_421,
        ),
        172_423,
    )

    assert bot.events == [("copy_message", (172_423, 172_411, 172_421))], (
        "scream delivery changed the source or destination message identifiers"
    )


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (
            TelegramForbiddenError(
                method=CopyMessage(chat_id=172_427, from_chat_id=172_429, message_id=172_433),
                message="recipient unavailable",
            ),
            TelegramRecipientUnavailableError,
        ),
        (
            TelegramBadRequest(
                method=CopyMessage(chat_id=172_427, from_chat_id=172_429, message_id=172_433),
                message="source rejected",
            ),
            PermanentTelegramDeliveryError,
        ),
        (
            TelegramNetworkError(
                method=CopyMessage(chat_id=172_427, from_chat_id=172_429, message_id=172_433),
                message="network unavailable",
            ),
            TelegramDeliveryError,
        ),
    ],
)
async def test_classifies_copy_failures_for_temporal_retries(
    failure: BaseException,
    expected_error: type[BaseException],
) -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=failure,
    )

    with pytest.raises(expected_error):
        await AiogramTelegramMessageSender(bot).copy(
            ScreamRequest(
                locale="en",
                source_chat_id=172_429,
                source_message_id=172_433,
            ),
            172_427,
        )
