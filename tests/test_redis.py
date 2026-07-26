from unittest.mock import AsyncMock, Mock

import pytest
from redis.asyncio import Redis

from sein_zum_tode.ingress.redis import RedisKeyValueClient


async def test_redis_client_sets_value_with_ttl() -> None:
    redis = Mock(spec=Redis)
    redis.set = AsyncMock(return_value=True)
    client = RedisKeyValueClient(redis)

    result = await client.set("key", "value", ex=60)

    assert result is True
    redis.set.assert_awaited_once_with("key", "value", ex=60)


async def test_redis_client_rejects_unexpected_response() -> None:
    redis = Mock(spec=Redis)
    redis.set = AsyncMock(return_value=object())
    client = RedisKeyValueClient(redis)

    with pytest.raises(TypeError, match="Unexpected Redis SET response"):
        await client.set("key", "value", ex=60)
