import pytest
from redis.exceptions import ConnectionError

from sein_zum_tode.infrastructure.redis_documents import (
    PydanticJsonCodec,
    RedisJsonDocumentStore,
)
from sein_zum_tode.ingress.errors import UpdateStoreError
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.store import TelegramUpdateStore
from tests.support import RedisDouble, TelegramUpdates, UserResolverDouble

pytestmark = pytest.mark.fast


async def test_stores_the_complete_update_and_its_route() -> None:
    update = TelegramUpdates.message(
        update_id=983,
        user_id=98_333,
        chat_id=98_339,
        text="Jived fox nymph grabs",
        chat_type="private",
    )
    redis = RedisDouble(
        get_result=None,
        set_result=b"STORED-991",
        delete_result=0,
    )
    resolver = UserResolverDouble(98_333)
    store = TelegramUpdateStore(
        updates=RedisJsonDocumentStore(
            redis=redis.client(),
            codec=PydanticJsonCodec(
                model=type(update),
                by_alias=True,
                exclude_none=True,
            ),
            document_name="Telegram update",
        ),
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
                "set",
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
    redis = RedisDouble(
        get_result=None,
        set_result=redis_outcome,
        delete_result=0,
    )
    store = TelegramUpdateStore(
        updates=RedisJsonDocumentStore(
            redis=redis.client(),
            codec=PydanticJsonCodec(model=type(update)),
            document_name="Telegram update",
        ),
        user_resolver=UserResolverDouble(101_323),
        bot_id=101_347,
        ttl_seconds=1019,
        key_prefix="telegram:pulsars",
    )

    with pytest.raises(UpdateStoreError):
        await store.store(update)
