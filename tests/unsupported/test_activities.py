import pytest

from sein_zum_tode.bot.errors import InvalidStoredPayloadError
from sein_zum_tode.bot.models import PrepareResponseInput, TelegramResponse
from sein_zum_tode.unsupported.activities import PrepareUnsupportedResponseActivity
from sein_zum_tode.unsupported.models import (
    UnsupportedUpdateContent,
    UnsupportedUpdateSession,
)
from tests.support import (
    BotContents,
    MortalMemory,
    SilentLogger,
    TelegramMemory,
    UnsupportedSessionMemory,
    mortal,
)

pytestmark = pytest.mark.fast


def content(initial_silence_count: int) -> UnsupportedUpdateContent:
    return UnsupportedUpdateContent(
        initial_silence_count=initial_silence_count,
        stanzas=(("First line", "Second line"),),
    )


def telegram_memory() -> TelegramMemory:
    return TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )


async def test_refreshes_the_session_ttl_without_preparing_an_initial_response() -> None:
    sessions = UnsupportedSessionMemory()
    responses = telegram_memory()
    subject = PrepareUnsupportedResponseActivity(
        sessions=sessions,
        responses=responses.response_documents,
        content=content(initial_silence_count=10),
        bot_content=BotContents.debug(),
        mortals=MortalMemory(),
        bot_id=277,
        session_ttl_seconds=3600,
        response_ttl_seconds=281,
        logger=SilentLogger(),
    )

    outcomes = [
        await subject.prepare_unsupported(
            PrepareResponseInput(
                update_key=f"telegram:update:{update_id}",
                response_key=f"telegram:update:{update_id}:response",
                chat_id=283,
                user_id=283,
            )
        )
        for update_id in range(10)
    ]

    assert (
        [outcome.response_prepared for outcome in outcomes],
        sessions.sessions["telegram:unsupported:277:283"].ignored_updates,
        [event[-1] for event in sessions.events if event[0] == "store_unsupported_session"],
        responses.events,
    ) == (
        [False] * 10,
        10,
        [3600] * 10,
        [],
    ), "silent unsupported updates produced a response or failed to refresh their TTL"


async def test_prepares_the_first_poem_line_after_the_silence_threshold() -> None:
    sessions = UnsupportedSessionMemory()
    sessions.sessions["telegram:unsupported:293:307"] = UnsupportedUpdateSession(ignored_updates=10)
    responses = telegram_memory()
    subject = PrepareUnsupportedResponseActivity(
        sessions=sessions,
        responses=responses.response_documents,
        content=content(initial_silence_count=10),
        bot_content=BotContents.debug(),
        mortals=MortalMemory(),
        bot_id=293,
        session_ttl_seconds=3600,
        response_ttl_seconds=311,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:update:313",
        response_key="telegram:update:313:response",
        chat_id=307,
        user_id=307,
        callback_query_id="callback-317",
    )

    actual = await subject.prepare_unsupported(input)

    assert (
        actual.response_prepared,
        responses.responses[input.response_key],
        responses.events,
    ) == (
        True,
        TelegramResponse(
            chat_id=307,
            text="First line",
            callback_query_id="callback-317",
        ),
        [
            (
                "store_response",
                input.response_key,
                TelegramResponse(
                    chat_id=307,
                    text="First line",
                    callback_query_id="callback-317",
                ),
                311,
            )
        ],
    ), "the eleventh unsupported update did not prepare the first poem line"


class InvalidSessionMemory(UnsupportedSessionMemory):
    async def load(self, key: str) -> UnsupportedUpdateSession | None:
        raise InvalidStoredPayloadError("shattered unsupported session", key)


async def test_restarts_an_invalid_session_and_falls_back_to_the_chat_id() -> None:
    sessions = InvalidSessionMemory()
    subject = PrepareUnsupportedResponseActivity(
        sessions=sessions,
        responses=telegram_memory().response_documents,
        content=content(initial_silence_count=1),
        bot_content=BotContents.debug(),
        mortals=MortalMemory(),
        bot_id=331,
        session_ttl_seconds=3600,
        response_ttl_seconds=337,
        logger=SilentLogger(),
    )

    actual = await subject.prepare_unsupported(
        PrepareResponseInput(
            update_key="telegram:update:347",
            response_key="telegram:update:347:response",
            chat_id=349,
        )
    )

    assert (
        actual.response_prepared,
        sessions.sessions["telegram:unsupported:331:349"].ignored_updates,
    ) == (False, 1), "an invalid session prevented a fresh silent cycle"


async def test_prepares_localized_help_for_initial_text_and_keeps_counting() -> None:
    sessions = UnsupportedSessionMemory()
    responses = telegram_memory()
    subject = PrepareUnsupportedResponseActivity(
        sessions=sessions,
        responses=responses.response_documents,
        content=content(initial_silence_count=10),
        bot_content=BotContents.debug(),
        mortals=MortalMemory({353: mortal(id=353, locale="ru")}),
        bot_id=347,
        session_ttl_seconds=3600,
        response_ttl_seconds=359,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:update:353",
        response_key="telegram:update:353:response",
        chat_id=353,
        user_id=353,
        is_text_message=True,
    )

    actual = await subject.prepare_unsupported(input)

    assert (
        actual.response_prepared,
        sessions.sessions["telegram:unsupported:347:353"].ignored_updates,
        responses.responses[input.response_key].text,
    ) == (
        True,
        1,
        "Нажмите /help, чтобы узнать, как пользоваться ботом.",
    ), "unsupported text stayed silent or stopped advancing the Verfall counter"
