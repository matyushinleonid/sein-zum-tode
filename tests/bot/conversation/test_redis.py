import pytest
from redis.exceptions import ConnectionError

from sein_zum_tode.bot.conversation.models import ConversationState
from sein_zum_tode.bot.conversation.redis import RedisConversationStateRepository
from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from tests.support import BotContents, RedisDouble

pytestmark = pytest.mark.fast


def conversation_state() -> ConversationState:
    content = BotContents.debug()
    return ConversationState.begin(
        content=content,
        localized=content.default(),
        user_id=211_111,
        chat_id=211_117,
    )


@pytest.mark.parametrize("representation", ["text", "bytes"])
async def test_loads_each_redis_representation_of_a_conversation(
    representation: str,
) -> None:
    expected = conversation_state()
    payload = expected.model_dump_json()
    redis = RedisDouble(
        get_result=payload if representation == "text" else payload.encode(),
        set_result=True,
        delete_result=0,
    )
    repository = RedisConversationStateRepository(redis)

    actual = await repository.load_conversation("telegram:conversation:2113")

    assert actual == expected, "Redis repository changed the snapshotted conversation"


async def test_returns_no_conversation_after_redis_ttl_expiration() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)
    repository = RedisConversationStateRepository(redis)

    actual = await repository.load_conversation("telegram:conversation:2129")

    assert actual is None, "repository invented a conversation after its TTL expired"


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        object(),
    ],
)
async def test_rejects_an_undecodable_conversation(payload: object) -> None:
    redis = RedisDouble(get_result=payload, set_result=True, delete_result=0)
    repository = RedisConversationStateRepository(redis)

    with pytest.raises((InvalidStoredPayloadError, TypeError)):
        await repository.load_conversation("telegram:conversation:2131")


async def test_stores_the_conversation_snapshot_with_inactivity_ttl() -> None:
    state = conversation_state()
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)
    repository = RedisConversationStateRepository(redis)

    await repository.store_conversation(
        key="telegram:conversation:2137",
        state=state,
        ttl_seconds=2141,
    )

    assert redis.events == [
        (
            "set",
            "telegram:conversation:2137",
            state.model_dump_json(),
            2141,
        )
    ], "conversation repository used a wrong key, payload, or inactivity TTL"


@pytest.mark.parametrize(
    "redis_outcome",
    [
        None,
        ConnectionError("write orbit collapsed 2143"),
    ],
)
async def test_rejects_every_unsuccessful_conversation_write(
    redis_outcome: object,
) -> None:
    redis = RedisDouble(
        get_result=None,
        set_result=redis_outcome,
        delete_result=0,
    )
    repository = RedisConversationStateRepository(redis)

    with pytest.raises(PayloadRepositoryError):
        await repository.store_conversation(
            key="telegram:conversation:2153",
            state=conversation_state(),
            ttl_seconds=2161,
        )


async def test_translates_a_redis_conversation_read_failure() -> None:
    redis = RedisDouble(
        get_result=ConnectionError("read orbit collapsed 2179"),
        set_result=True,
        delete_result=0,
    )
    repository = RedisConversationStateRepository(redis)

    with pytest.raises(PayloadRepositoryError):
        await repository.load_conversation("telegram:conversation:2203")
