from typing import cast

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import CopyMessage, SendAudio, SendMessage
from aiogram.types import (
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    ReplyMarkupUnion,
)

from sein_zum_tode.bot.errors import (
    PermanentTelegramDeliveryError,
    TelegramDeliveryError,
    TelegramRateLimitedError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import (
    TelegramAttachment,
    TelegramAttachmentKind,
    TelegramButton,
    TelegramKeyboardMode,
    TelegramResponse,
)
from sein_zum_tode.bot.sender import AiogramTelegramMessageSender
from sein_zum_tode.broadcasts.models import ScreamRequest
from tests.support import TelegramBotDouble

pytestmark = pytest.mark.fast


class CustomEmojiRejectedBot(TelegramBotDouble):
    def __init__(self, failure: TelegramBadRequest) -> None:
        super().__init__(
            updates=[],
            delete_result=None,
            receive_result=None,
            send_result=None,
        )
        self.failure = failure

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: ReplyMarkupUnion | None = None,
    ) -> object:
        self.events.append(("send_message", (chat_id, text, parse_mode, reply_markup)))
        if len(self.events) == 1:
            raise self.failure
        return None


class CustomEmojiRejectedAudioBot(TelegramBotDouble):
    def __init__(self, failure: TelegramBadRequest) -> None:
        super().__init__(
            updates=[],
            delete_result=None,
            receive_result=None,
            send_result=None,
        )
        self.failure = failure
        self.audio_attempts = 0

    async def send_audio(
        self,
        *,
        chat_id: int,
        audio: str,
        caption: str,
        parse_mode: str | None = None,
        reply_markup: ReplyMarkupUnion | None = None,
    ) -> object:
        self.audio_attempts += 1
        self.events.append(("send_audio", (chat_id, audio, caption, parse_mode, reply_markup)))
        if self.audio_attempts == 1:
            raise self.failure
        return None


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


async def test_sends_a_one_time_reply_keyboard_below_the_input() -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )
    sender = AiogramTelegramMessageSender(bot)

    await sender.send(
        TelegramResponse(
            chat_id=171_019,
            text="Choose",
            keyboard=(
                (
                    TelegramButton(
                        text="Daily · 09:00",
                        callback_data="notifications:daily",
                    ),
                ),
            ),
            keyboard_mode=TelegramKeyboardMode.REPLY,
        )
    )

    send_arguments = cast(tuple[object, ...], bot.events[0][1])
    reply_markup = cast(ReplyKeyboardMarkup, send_arguments[3])
    assert (
        reply_markup.keyboard[0][0].text,
        reply_markup.resize_keyboard,
        reply_markup.one_time_keyboard,
        reply_markup.is_persistent,
    ) == (
        "Daily · 09:00",
        True,
        True,
        False,
    ), "reply keyboard was not rendered as a compact one-time Telegram keyboard"


async def test_removes_a_reply_keyboard_after_the_selection() -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )
    sender = AiogramTelegramMessageSender(bot)

    await sender.send(
        TelegramResponse(
            chat_id=171_029,
            text="Selected",
            remove_reply_keyboard=True,
        )
    )

    send_arguments = cast(tuple[object, ...], bot.events[0][1])
    reply_markup = cast(ReplyKeyboardRemove, send_arguments[3])
    assert reply_markup.remove_keyboard is True, (
        "reply keyboard remained visible after its selection was handled"
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


async def test_retries_a_rejected_custom_emoji_message_with_plain_fallback() -> None:
    method = SendMessage(chat_id=172_223, text="custom emoji")
    bot = CustomEmojiRejectedBot(
        TelegramBadRequest(method=method, message="custom emoji entities are not allowed")
    )
    sender = AiogramTelegramMessageSender(bot)

    await sender.send(
        TelegramResponse(
            chat_id=172_223,
            text='<tg-emoji emoji-id="227">🚶</tg-emoji>\n5 days remain',
            parse_mode="HTML",
            fallback_text="🚶\n5 days remain",
        )
    )

    assert bot.events == [
        (
            "send_message",
            (
                172_223,
                '<tg-emoji emoji-id="227">🚶</tg-emoji>\n5 days remain',
                "HTML",
                None,
            ),
        ),
        ("send_message", (172_223, "🚶\n5 days remain", None, None)),
    ], "custom emoji rejection prevented delivery of the plain notification fallback"


@pytest.mark.parametrize(
    ("kind", "expected_method"),
    [
        (TelegramAttachmentKind.AUDIO, "send_audio"),
        (TelegramAttachmentKind.PHOTO, "send_photo"),
        (TelegramAttachmentKind.VIDEO, "send_video"),
        (TelegramAttachmentKind.DOCUMENT, "send_document"),
    ],
)
async def test_sends_each_s3_attachment_kind_with_a_caption(
    kind: TelegramAttachmentKind,
    expected_method: str,
) -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )
    response = TelegramResponse(
        chat_id=172_229,
        text="Rare emoji\n5 days remain",
        parse_mode="HTML",
        attachment=TelegramAttachment(
            kind=kind,
            url="https://storage.example.com/reward.bin",
        ),
    )

    await AiogramTelegramMessageSender(bot).send(response)

    assert bot.events == [
        (
            expected_method,
            (
                172_229,
                "https://storage.example.com/reward.bin",
                "Rare emoji\n5 days remain",
                "HTML",
                None,
            ),
        )
    ], "S3 reward was not sent through its configured Telegram media method"


async def test_sends_a_reward_prelude_before_the_main_notification() -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )

    await AiogramTelegramMessageSender(bot).send(
        TelegramResponse(
            chat_id=172_231,
            text="Rare emoji\n5 days remain",
            prelude_text="👑 Mythic!",
            attachment=TelegramAttachment(
                kind=TelegramAttachmentKind.AUDIO,
                url="https://storage.example.com/stupa.mp3",
            ),
        )
    )

    assert bot.events == [
        ("send_message", (172_231, "👑 Mythic!", None, None)),
        (
            "send_audio",
            (
                172_231,
                "https://storage.example.com/stupa.mp3",
                "Rare emoji\n5 days remain",
                None,
                None,
            ),
        ),
    ], "reward prelude was not delivered as a separate message before the notification"


async def test_retries_only_the_media_caption_without_custom_emoji() -> None:
    method = SendAudio(
        chat_id=172_233,
        audio="https://storage.example.com/stupa.mp3",
        caption="custom emoji",
    )
    bot = CustomEmojiRejectedAudioBot(
        TelegramBadRequest(method=method, message="custom emoji entities are not allowed")
    )

    await AiogramTelegramMessageSender(bot).send(
        TelegramResponse(
            chat_id=172_233,
            text='<tg-emoji emoji-id="227">🚶</tg-emoji>\n5 days remain',
            parse_mode="HTML",
            fallback_text="🚶\n5 days remain",
            prelude_text="👑 Mythic!",
            attachment=TelegramAttachment(
                kind=TelegramAttachmentKind.AUDIO,
                url="https://storage.example.com/stupa.mp3",
            ),
        )
    )

    assert bot.events == [
        ("send_message", (172_233, "👑 Mythic!", None, None)),
        (
            "send_audio",
            (
                172_233,
                "https://storage.example.com/stupa.mp3",
                '<tg-emoji emoji-id="227">🚶</tg-emoji>\n5 days remain',
                "HTML",
                None,
            ),
        ),
        (
            "send_audio",
            (
                172_233,
                "https://storage.example.com/stupa.mp3",
                "🚶\n5 days remain",
                None,
                None,
            ),
        ),
    ], "media fallback resent the prelude or failed to remove rejected custom emoji"


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


async def test_preserves_telegram_retry_after_for_response_delivery() -> None:
    method = SendMessage(chat_id=172_339, text="Wait for the orbit")
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=TelegramRetryAfter(
            method=method,
            message="too many requests",
            retry_after=17,
        ),
    )

    with pytest.raises(TelegramRateLimitedError) as captured:
        await AiogramTelegramMessageSender(bot).send(
            TelegramResponse(chat_id=172_339, text="Wait for the orbit")
        )

    assert captured.value.retry_after_seconds == 17, (
        "response delivery discarded Telegram's requested retry delay"
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


async def test_preserves_telegram_retry_after_for_broadcast_copy() -> None:
    method = CopyMessage(chat_id=172_425, from_chat_id=172_421, message_id=172_423)
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=TelegramRetryAfter(
            method=method,
            message="broadcast throttled",
            retry_after=29,
        ),
    )

    with pytest.raises(TelegramRateLimitedError) as captured:
        await AiogramTelegramMessageSender(bot).copy(
            ScreamRequest(
                locale="en",
                source_chat_id=172_421,
                source_message_id=172_423,
            ),
            172_425,
        )

    assert captured.value.retry_after_seconds == 29, (
        "broadcast copy discarded Telegram's requested retry delay"
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
