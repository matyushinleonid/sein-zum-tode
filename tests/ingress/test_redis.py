import pytest

from sein_zum_tode.ingress.redis import RedisKeyValueClient
from tests.support import RedisDouble

pytestmark = pytest.mark.fast


@pytest.mark.parametrize("response", [None, True, "OK-907", b"QUEUED-911"])
async def test_returns_every_documented_redis_set_response(response: object) -> None:
    redis = RedisDouble(get_result=None, set_result=response, delete_result=0)
    client = RedisKeyValueClient(redis)

    actual = await client.set("cipher:919", "quartz-929", ex=937)

    assert (actual, redis.events) == (
        response,
        [("set", "cipher:919", "quartz-929", 937)],
    ), "Redis adapter changed a valid SET response or its arguments"


async def test_rejects_an_undocumented_redis_set_response() -> None:
    redis = RedisDouble(get_result=None, set_result=object(), delete_result=0)
    client = RedisKeyValueClient(redis)

    with pytest.raises(TypeError):
        await client.set("cipher:941", "nebula-947", ex=953)
