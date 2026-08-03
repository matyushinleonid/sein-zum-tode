from pathlib import Path

import pytest
from redis.exceptions import ConnectionError

import sein_zum_tode.infrastructure.redis as redis_module
from sein_zum_tode.infrastructure.redis import RedisClientError, create_redis_transport
from tests.support import RedisDouble

pytestmark = pytest.mark.fast


def test_creates_an_acl_and_tls_redis_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()
    calls: list[dict[str, object]] = []

    def create_connection(**options: object) -> object:
        calls.append(options)
        return connection

    monkeypatch.setattr(redis_module, "Redis", create_connection)

    actual = create_redis_transport(
        host="redis-orbit.internal",
        port=887,
        database=19,
        username="mortal-redis",
        password="private-907",
        socket_connect_timeout_seconds=3.1,
        socket_timeout_seconds=5.3,
        max_connections=23,
        health_check_interval_seconds=29,
        tls=True,
        tls_verify=True,
        tls_ca_file=Path("/certificates/redis-ca-911.pem"),
        tls_certificate_file=Path("/certificates/redis-919.pem"),
        tls_private_key_file=Path("/certificates/redis-929.key"),
    )

    assert (actual, calls) == (
        connection,
        [
            {
                "host": "redis-orbit.internal",
                "port": 887,
                "db": 19,
                "username": "mortal-redis",
                "password": "private-907",
                "socket_connect_timeout": 3.1,
                "socket_timeout": 5.3,
                "max_connections": 23,
                "health_check_interval": 29,
                "ssl": True,
                "ssl_cert_reqs": "required",
                "ssl_check_hostname": True,
                "ssl_ca_certs": "/certificates/redis-ca-911.pem",
                "ssl_certfile": "/certificates/redis-919.pem",
                "ssl_keyfile": "/certificates/redis-929.key",
            }
        ],
    ), "Redis transport discarded ACL, limits, or TLS material"


def test_creates_a_plain_redis_transport_without_optional_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(redis_module, "Redis", lambda **options: calls.append(options))

    actual = create_redis_transport(
        host="redis-plain.internal",
        port=937,
        database=0,
        username=None,
        password="private-941",
        socket_connect_timeout_seconds=7.0,
        socket_timeout_seconds=11.0,
        max_connections=None,
        health_check_interval_seconds=0,
        tls=False,
        tls_verify=False,
        tls_ca_file=None,
        tls_certificate_file=None,
        tls_private_key_file=None,
    )

    actual_object: object = actual
    assert (actual_object, calls[0]["ssl_cert_reqs"], calls[0]["ssl_ca_certs"]) == (
        None,
        "none",
        None,
    ), "plain Redis transport unexpectedly required TLS material"


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


async def test_checks_redis_connectivity_without_reading_application_data() -> None:
    redis = RedisDouble(
        get_result=None,
        set_result=True,
        delete_result=0,
        ping_result=True,
    )

    actual = await redis.client().ping()

    assert (actual, redis.events) == (True, [("ping",)]), (
        "Redis health check accessed an application key or discarded PING"
    )


@pytest.mark.parametrize(
    ("operation", "label"),
    [
        ("get", "GET"),
        ("set", "SET"),
        ("delete", "DELETE"),
        ("ping", "PING"),
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
        ping_result=failure if operation == "ping" else True,
    )
    client = redis.client()

    with pytest.raises(RedisClientError):
        if operation == "get":
            await client.get("cipher:1013")
        elif operation == "set":
            await client.set("cipher:1013", "aurora-1019", 1021)
        elif operation == "delete":
            await client.delete(("cipher:1013",))
        else:
            await client.ping()


@pytest.mark.parametrize("deleted", [True, "one"])
async def test_rejects_each_undocumented_delete_response(deleted: object) -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=deleted)

    with pytest.raises(RedisClientError):
        await redis.client().delete(("cipher:1031",))
