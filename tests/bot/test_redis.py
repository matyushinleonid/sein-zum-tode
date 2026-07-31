import pytest
from redis.exceptions import ConnectionError

from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.redis import RedisTelegramPayloadRepository
from tests.support import RedisDouble, TelegramUpdates

pytestmark = pytest.mark.fast


@pytest.mark.parametrize("representation", ["text", "bytes"])
async def test_loads_a_telegram_update_from_each_redis_representation(
    representation: str,
) -> None:
    update = TelegramUpdates.message(
        update_id=1553,
        user_id=155_359,
        chat_id=155_363,
        text="Cozy lummox gives smart squid",
        chat_type="private",
    )
    payload = update.model_dump_json()
    redis = RedisDouble(
        get_result=payload if representation == "text" else payload.encode(),
        set_result=True,
        delete_result=0,
    )
    repository = RedisTelegramPayloadRepository(redis.client())

    actual = await repository.load_update("telegram:squid:1559")

    assert actual == update, "repository changed the Telegram update stored in Redis"


async def test_returns_no_update_for_an_expired_redis_key() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)
    repository = RedisTelegramPayloadRepository(redis.client())

    actual = await repository.load_update("telegram:expired:1567")

    assert actual is None, "repository invented an update for an expired key"


async def test_rejects_a_malformed_telegram_update() -> None:
    redis = RedisDouble(get_result="{}", set_result=True, delete_result=0)
    repository = RedisTelegramPayloadRepository(redis.client())

    with pytest.raises(InvalidStoredPayloadError):
        await repository.load_update("telegram:broken:1571")


async def test_stores_a_response_as_json_with_its_ttl() -> None:
    redis = RedisDouble(get_result=None, set_result=b"STORED-1579", delete_result=0)
    repository = RedisTelegramPayloadRepository(redis.client())
    response = TelegramResponse(chat_id=158_357, text="A very bad quack might jinx zippy fowls")

    await repository.store_response(
        key="telegram:response:1583",
        response=response,
        ttl_seconds=1597,
    )

    assert redis.events == [("set", "telegram:response:1583", response.model_dump_json(), 1597)], (
        "repository stored the response under a wrong key, JSON, or TTL"
    )


@pytest.mark.parametrize(
    "redis_outcome",
    [None, ConnectionError("redis rings collapsed 1601")],
)
async def test_rejects_every_unsuccessful_response_write(redis_outcome: object) -> None:
    redis = RedisDouble(get_result=None, set_result=redis_outcome, delete_result=0)
    repository = RedisTelegramPayloadRepository(redis.client())
    response = TelegramResponse(chat_id=160_163, text="Big fjords vex quick waltz nymph")

    with pytest.raises(PayloadRepositoryError):
        await repository.store_response(
            key="telegram:response:1607",
            response=response,
            ttl_seconds=1609,
        )


async def test_loads_a_telegram_response_from_redis() -> None:
    expected = TelegramResponse(chat_id=161_327, text="Waxy and quivering jocks fumble pizza")
    redis = RedisDouble(
        get_result=expected.model_dump_json(),
        set_result=True,
        delete_result=0,
    )
    repository = RedisTelegramPayloadRepository(redis.client())

    actual = await repository.load_response("telegram:response:1613")

    assert actual == expected, "repository changed the prepared response loaded from Redis"


async def test_returns_no_response_for_an_expired_redis_key() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)
    repository = RedisTelegramPayloadRepository(redis.client())

    actual = await repository.load_response("telegram:expired-response:1619")

    assert actual is None, "repository invented a response for an expired key"


async def test_rejects_a_malformed_telegram_response() -> None:
    redis = RedisDouble(
        get_result='{"chat_id":"Saturn"}',
        set_result=True,
        delete_result=0,
    )
    repository = RedisTelegramPayloadRepository(redis.client())

    with pytest.raises(InvalidStoredPayloadError):
        await repository.load_response("telegram:broken-response:1621")


async def test_deletes_all_ephemeral_payload_keys_together() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=2)
    repository = RedisTelegramPayloadRepository(redis.client())

    await repository.delete(("telegram:update:1627", "telegram:response:1637"))

    assert redis.events == [("delete", "telegram:update:1627", "telegram:response:1637")], (
        "repository failed to delete both ephemeral payload keys"
    )


async def test_translates_a_redis_delete_failure() -> None:
    redis = RedisDouble(
        get_result=None,
        set_result=True,
        delete_result=ConnectionError("delete orbit failed 1657"),
    )
    repository = RedisTelegramPayloadRepository(redis.client())

    with pytest.raises(PayloadRepositoryError):
        await repository.delete(("telegram:update:1663", "telegram:response:1667"))


async def test_translates_a_redis_read_failure() -> None:
    redis = RedisDouble(
        get_result=ConnectionError("read orbit failed 1669"),
        set_result=True,
        delete_result=0,
    )
    repository = RedisTelegramPayloadRepository(redis.client())

    with pytest.raises(PayloadRepositoryError):
        await repository.load_update("telegram:update:1693")


async def test_translates_an_undocumented_redis_get_response() -> None:
    redis = RedisDouble(get_result=object(), set_result=True, delete_result=0)
    repository = RedisTelegramPayloadRepository(redis.client())

    with pytest.raises(PayloadRepositoryError):
        await repository.load_update("telegram:update:1697")
