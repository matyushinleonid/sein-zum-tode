import pytest
from aiogram.enums import UpdateType
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetUpdates

from sein_zum_tode.ingress.errors import UpdateSourceError
from sein_zum_tode.ingress.source import AiogramUpdateSource
from tests.support import TelegramBotDouble, TelegramUpdates

pytestmark = pytest.mark.fast


async def test_preserves_pending_updates_when_preparing_long_polling() -> None:
    bot = TelegramBotDouble(
        updates=[],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=29,
        request_timeout_seconds=43,
    )

    await source.prepare()

    assert bot.events == [("delete_webhook", False)], (
        "source discarded Telegram updates while removing the webhook"
    )


async def test_requests_all_known_update_types_with_the_given_offset() -> None:
    update = TelegramUpdates.message(
        update_id=967,
        user_id=97_109,
        chat_id=97_111,
        text="Waltz, bad nymph",
        chat_type="private",
    )
    bot = TelegramBotDouble(
        updates=[update],
        delete_result=None,
        receive_result=None,
        send_result=None,
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=31,
        request_timeout_seconds=47,
    )

    actual = await source.receive(961)

    assert (actual, bot.events) == (
        [update],
        [
            (
                "get_updates",
                {
                    "offset": 961,
                    "timeout": 31,
                    "allowed_updates": [kind.value for kind in UpdateType],
                    "request_timeout": 47,
                },
            )
        ],
    ), "source narrowed Telegram update types or altered long-polling arguments"


@pytest.mark.parametrize("operation", ["prepare", "receive"])
async def test_translates_aiogram_failures_at_the_source_boundary(operation: str) -> None:
    failure = TelegramNetworkError(method=GetUpdates(), message="ion storm 977")
    bot = TelegramBotDouble(
        updates=[],
        delete_result=failure if operation == "prepare" else None,
        receive_result=failure,
        send_result=None,
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=37,
        request_timeout_seconds=53,
    )
    call = source.prepare() if operation == "prepare" else source.receive(None)

    with pytest.raises(UpdateSourceError):
        await call
