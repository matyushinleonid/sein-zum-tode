import pytest
from redis.exceptions import ConnectionError

from sein_zum_tode.infrastructure.redis import RedisClientError
from tests.support import RedisDouble

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("stored", "label"),
    [
        (True, "boolean"),
        ("OK-907", "text"),
        (b"QUEUED-911", "bytes"),
    ],
)
async def test_sets_text_with_ttl_for_each_success_response(
    stored: object,
    label: str,
) -> None:
    redis = RedisDouble(get_result=None, set_result=stored, delete_result=0)

    await redis.client().set("cipher:919", "quartz-929", 937)

    assert redis.events == [("set", "cipher:919", "quartz-929", 937)], (
        f"client changed SET arguments for the {label} success response"
    )


@pytest.mark.parametrize(
    ("stored", "label"),
    [
        (None, "missing"),
        (False, "negative"),
        (object(), "undocumented"),
    ],
)
async def test_rejects_each_unsuccessful_set_response(
    stored: object,
    label: str,
) -> None:
    redis = RedisDouble(get_result=None, set_result=stored, delete_result=0)

    with pytest.raises(RedisClientError):
        await redis.client().set("cipher:941", "nebula-947", 953)

    assert redis.events, f"client did not issue SET for the {label} response"


@pytest.mark.parametrize(
    ("stored", "expected", "label"),
    [
        ("vortex-967", "vortex-967", "text"),
        (b"vortex-971", "vortex-971", "bytes"),
        (None, None, "missing"),
    ],
)
async def test_gets_normalized_text_for_each_redis_representation(
    stored: object,
    expected: str | None,
    label: str,
) -> None:
    redis = RedisDouble(get_result=stored, set_result=True, delete_result=0)

    actual = await redis.client().get("cipher:977")

    assert actual == expected, f"client changed the {label} GET representation"


@pytest.mark.parametrize(
    ("stored", "label"),
    [
        (object(), "undocumented"),
        (b"\xff", "non-UTF-8"),
    ],
)
async def test_rejects_each_invalid_get_response(stored: object, label: str) -> None:
    redis = RedisDouble(get_result=stored, set_result=True, delete_result=0)

    with pytest.raises(RedisClientError):
        await redis.client().get("cipher:983")

    assert redis.events, f"client did not issue GET for the {label} response"


async def test_deletes_all_keys_in_one_redis_command() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=2)

    await redis.client().delete(("cipher:991", "cipher:997"))

    assert redis.events == [("delete", "cipher:991", "cipher:997")], (
        "client did not delete all keys together"
    )


@pytest.mark.parametrize(
    ("operation", "label"),
    [
        ("get", "GET"),
        ("set", "SET"),
        ("delete", "DELETE"),
    ],
)
async def test_translates_each_redis_transport_failure(
    operation: str,
    label: str,
) -> None:
    failure = ConnectionError(f"{label} orbit collapsed 1009")
    redis = RedisDouble(
        get_result=failure if operation == "get" else None,
        set_result=failure if operation == "set" else True,
        delete_result=failure if operation == "delete" else 0,
    )
    client = redis.client()

    with pytest.raises(RedisClientError):
        if operation == "get":
            await client.get("cipher:1013")
        elif operation == "set":
            await client.set("cipher:1013", "aurora-1019", 1021)
        else:
            await client.delete(("cipher:1013",))


@pytest.mark.parametrize("deleted", [True, "one"])
async def test_rejects_each_undocumented_delete_response(deleted: object) -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=deleted)

    with pytest.raises(RedisClientError):
        await redis.client().delete(("cipher:1031",))
