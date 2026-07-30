import pytest

from sein_zum_tode.bot.conversation.activities import (
    RecordTelegramConversationAnswerActivity,
    StartTelegramConversationActivity,
)
from sein_zum_tode.bot.conversation.models import (
    ConversationState,
    ConversationTurnKind,
    RecordConversationAnswerInput,
    StartConversationInput,
)
from sein_zum_tode.bot.errors import InvalidStoredPayloadError
from sein_zum_tode.bot.models import TelegramResponse
from tests.support import (
    BotContents,
    ConversationMemory,
    ConversationRepositoryDouble,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
)

pytestmark = pytest.mark.fast


def conversation_state() -> ConversationState:
    content = BotContents.debug()
    return ConversationState.begin(
        content=content,
        localized=content.default(),
        user_id=223_721,
        chat_id=223_727,
    )


def record_activity(
    *,
    updates: object,
    conversations: object,
    responses: object,
) -> RecordTelegramConversationAnswerActivity:
    return RecordTelegramConversationAnswerActivity(
        updates=updates,
        conversations=conversations,
        responses=responses,
        conversation_ttl_seconds=2237,
        response_ttl_seconds=2239,
        privacy_response_ttl_seconds=2243,
        logger=SilentLogger(),
    )


async def test_starts_with_a_redis_snapshot_and_two_prepared_messages() -> None:
    content = BotContents.debug()
    memory = ConversationMemory()
    subject = StartTelegramConversationActivity(
        content=content,
        conversations=memory,
        responses=memory,
        conversation_ttl_seconds=2243,
        response_ttl_seconds=2251,
        privacy_response_ttl_seconds=2267,
        logger=SilentLogger(),
    )

    actual = await subject.start(
        StartConversationInput(
            conversation_key="telegram:conversation:2269",
            user_id=226_973,
            chat_id=226_979,
        )
    )

    state = memory.conversations["telegram:conversation:2269"]
    assert (
        actual.response_keys,
        actual.privacy_response_key,
        state.content_version,
        memory.responses,
    ) == (
        (
            "telegram:conversation:2269:initial:0",
            "telegram:conversation:2269:initial:1",
        ),
        "telegram:conversation:2269:privacy",
        "debug-cosmos-v1",
        {
            "telegram:conversation:2269:initial:0": TelegramResponse(
                chat_id=226_979,
                text="mock conversation started",
            ),
            "telegram:conversation:2269:initial:1": TelegramResponse(
                chat_id=226_979,
                text="q1?",
            ),
            "telegram:conversation:2269:privacy": TelegramResponse(
                chat_id=226_979,
                text="your answers were deleted from our system",
            ),
        },
    ), "conversation start failed to snapshot content or prepare its ordered messages"
    assert [
        event[-1] for event in memory.events if event[0] in {"store_conversation", "store_response"}
    ] == [
        2243,
        2251,
        2251,
        2267,
    ], "conversation start assigned the wrong TTL to stored private data"


async def test_records_text_and_refreshes_only_conversation_privacy_data() -> None:
    update_key = "telegram:answer:2273"
    state = conversation_state()
    memory = ConversationMemory(
        updates={
            update_key: TelegramUpdates.message(
                update_id=2273,
                user_id=state.user_id,
                chat_id=state.chat_id,
                text="Polaris",
                chat_type="private",
            )
        },
        conversations={"telegram:conversation:2273": state},
    )
    subject = record_activity(
        updates=memory,
        conversations=memory,
        responses=memory,
    )

    actual = await subject.record(
        RecordConversationAnswerInput(
            conversation_key="telegram:conversation:2273",
            update_key=update_key,
            user_id=state.user_id,
        )
    )

    saved = memory.conversations["telegram:conversation:2273"]
    assert (
        actual.kind,
        actual.response_keys,
        saved.current_question_index,
        saved.questions[0].answer,
        memory.responses,
    ) == (
        ConversationTurnKind.QUESTION,
        ("telegram:answer:2273:conversation-response:0",),
        1,
        "Polaris",
        {
            "telegram:answer:2273:conversation-response:0": TelegramResponse(
                chat_id=state.chat_id,
                text="q2?",
            ),
            "telegram:conversation:2273:privacy": TelegramResponse(
                chat_id=state.chat_id,
                text="your answers were deleted from our system",
            ),
        },
    ), "accepted text did not advance state or prepare the next question"
    assert [
        event[-1] for event in memory.events if event[0] in {"store_conversation", "store_response"}
    ] == [
        2237,
        2239,
        2243,
    ], "accepted text failed to restart inactivity and privacy response TTLs"


async def test_splits_a_large_final_summary_into_deliverable_messages() -> None:
    first = conversation_state().apply_answer(
        update_key="telegram:answer:2281",
        text="Deneb",
    )
    update_key = "telegram:answer:2287"
    memory = ConversationMemory(
        updates={
            update_key: TelegramUpdates.message(
                update_id=2287,
                user_id=first.state.user_id,
                chat_id=first.state.chat_id,
                text="S" * 4096,
                chat_type="private",
            )
        },
        conversations={"telegram:conversation:2287": first.state},
    )
    subject = record_activity(
        updates=memory,
        conversations=memory,
        responses=memory,
    )

    actual = await subject.record(
        RecordConversationAnswerInput(
            conversation_key="telegram:conversation:2287",
            update_key=update_key,
            user_id=first.state.user_id,
        )
    )

    response_parts = tuple(memory.responses[key].text for key in actual.response_keys)
    assert (
        actual.kind,
        len(actual.response_keys),
        all(len(part) <= 4096 for part in response_parts),
        "".join(response_parts),
    ) == (
        ConversationTurnKind.COMPLETED,
        2,
        True,
        memory.conversations["telegram:conversation:2287"].summary(),
    ), "completed conversation lost or oversized its temporary summary"


@pytest.mark.parametrize(
    "update_outcome",
    [
        None,
        InvalidStoredPayloadError("private update shattered 2293"),
        TelegramUpdates.message(
            update_id=2297,
            user_id=223_721,
            chat_id=223_727,
            text=None,
            chat_type="private",
        ),
        TelegramUpdates.message(
            update_id=2309,
            user_id=223_721,
            chat_id=-223_727,
            text="Group answer",
            chat_type="group",
        ),
    ],
)
async def test_ignores_input_that_is_not_a_private_text_message(
    update_outcome: object,
) -> None:
    state = conversation_state()
    conversations = ConversationRepositoryDouble(load_result=state)
    updates = TelegramMemory(
        update_result=update_outcome,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    responses = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    subject = record_activity(
        updates=updates,
        conversations=conversations,
        responses=responses,
    )

    actual = await subject.record(
        RecordConversationAnswerInput(
            conversation_key="telegram:conversation:2309",
            update_key="telegram:update:2311",
            user_id=state.user_id,
        )
    )

    assert (
        actual.kind,
        conversations.events,
        responses.events,
    ) == (
        ConversationTurnKind.IGNORED,
        [("load_conversation", "telegram:conversation:2309")],
        [],
    ), "unsupported input advanced the question or refreshed conversation TTL"


@pytest.mark.parametrize(
    "conversation_outcome",
    [
        None,
        InvalidStoredPayloadError("conversation snapshot shattered 2333"),
    ],
)
async def test_reports_an_expired_or_invalid_conversation(
    conversation_outcome: object,
) -> None:
    conversations = ConversationRepositoryDouble(load_result=conversation_outcome)
    updates = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    responses = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    subject = record_activity(
        updates=updates,
        conversations=conversations,
        responses=responses,
    )

    actual = await subject.record(
        RecordConversationAnswerInput(
            conversation_key="telegram:conversation:2339",
            update_key="telegram:update:2341",
            user_id=234_149,
        )
    )

    assert (
        actual.kind,
        updates.events,
        responses.events,
    ) == (
        ConversationTurnKind.EXPIRED,
        [],
        [],
    ), "expired conversation read or wrote Telegram update and response data"
