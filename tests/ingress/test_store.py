import pytest
from redis.exceptions import ConnectionError

from sein_zum_tode.ingress.errors import UpdateStoreError
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.store import RedisUpdateStore
from tests.support import KeyValueDouble, TelegramUpdates, UserResolverDouble

pytestmark = pytest.mark.fast


async def test_stores_the_complete_update_and_its_route() -> None:
    update = TelegramUpdates.message(
        update_id=983,
        user_id=98_333,
        chat_id=98_339,
        text="Jived fox nymph grabs",
        chat_type="private",
    )
    redis = KeyValueDouble([b"STORED-991"])
    resolver = UserResolverDouble(98_333)
    store = RedisUpdateStore(
        redis=redis,
        user_resolver=resolver,
        bot_id=98_347,
        ttl_seconds=997,
        key_prefix="telegram:constellations",
    )

    actual = await store.store(update)

    assert (actual, redis.events, resolver.events) == (
        StoredUpdate(
            update_id=983,
            key="telegram:constellations:98347:983",
            ttl_seconds=997,
            user_id=98_333,
        ),
        [
            (
                "telegram:constellations:98347:983",
                update.model_dump_json(by_alias=True, exclude_none=True),
                997,
            )
        ],
        [983],
    ), "store lost Telegram payload, TTL, key identity, or user route"


@pytest.mark.parametrize(
    "redis_outcome",
    [None, ConnectionError("magnetosphere unavailable 1009")],
)
async def test_rejects_every_unsuccessful_redis_write(redis_outcome: object) -> None:
    update = TelegramUpdates.message(
        update_id=1013,
        user_id=101_323,
        chat_id=101_333,
        text="Glib jocks quiz",
        chat_type="private",
    )
    store = RedisUpdateStore(
        redis=KeyValueDouble([redis_outcome]),
        user_resolver=UserResolverDouble(101_323),
        bot_id=101_347,
        ttl_seconds=1019,
        key_prefix="telegram:pulsars",
    )

    with pytest.raises(UpdateStoreError):
        await store.store(update)
