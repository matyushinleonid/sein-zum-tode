from collections.abc import Callable
from unittest.mock import create_autospec

import pytest
from aiogram.types import Update
from redis.exceptions import ConnectionError

from sein_zum_tode.ingress.errors import UpdateStoreError
from sein_zum_tode.ingress.ports import KeyValueClient
from sein_zum_tode.ingress.store import RedisUpdateStore


async def test_store_writes_complete_update_and_refreshes_ttl(
    make_update: Callable[[int, str], Update],
) -> None:
    redis = create_autospec(KeyValueClient, instance=True)
    redis.set.return_value = True
    store = RedisUpdateStore(
        redis=redis,
        bot_id=42,
        ttl_seconds=600,
    )
    update = make_update(17, "sensitive text")

    first = await store.store(update)
    second = await store.store(update)

    assert first == second
    assert first.update_id == 17
    assert first.key == "telegram:updates:42:17"
    assert first.ttl_seconds == 600
    assert redis.set.await_count == 2
    for call in redis.set.await_args_list:
        key, payload = call.args
        assert key == "telegram:updates:42:17"
        assert call.kwargs == {"ex": 600}
        restored = Update.model_validate_json(payload)
        assert restored == update
        assert '"text":"sensitive text"' in payload
        assert '"from":' in payload


async def test_store_raises_when_redis_rejects_write(
    make_update: Callable[[int, str], Update],
) -> None:
    redis = create_autospec(KeyValueClient, instance=True)
    redis.set.return_value = None
    store = RedisUpdateStore(redis, bot_id=42, ttl_seconds=600)

    with pytest.raises(UpdateStoreError, match="did not store Telegram update 17"):
        await store.store(make_update(17, "sensitive"))


async def test_store_wraps_redis_error(
    make_update: Callable[[int, str], Update],
) -> None:
    redis = create_autospec(KeyValueClient, instance=True)
    redis.set.side_effect = ConnectionError("unavailable")
    store = RedisUpdateStore(redis, bot_id=42, ttl_seconds=600)

    with pytest.raises(UpdateStoreError, match="Failed to store Telegram update 17"):
        await store.store(make_update(17, "sensitive"))
