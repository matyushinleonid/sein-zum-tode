from collections.abc import Awaitable
from pathlib import Path
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError


class RedisTransport(Protocol):
    def ping(self) -> Awaitable[bool]: ...

    def get(self, name: str) -> Awaitable[str | bytes | None]: ...

    def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
    ) -> Awaitable[bool | str | bytes | None]: ...

    def delete(self, *names: str) -> Awaitable[int]: ...


class RedisClientError(Exception):
    pass


def create_redis_transport(
    *,
    host: str,
    port: int,
    database: int,
    username: str | None,
    password: str,
    socket_connect_timeout_seconds: float,
    socket_timeout_seconds: float,
    max_connections: int | None,
    health_check_interval_seconds: int,
    tls: bool,
    tls_verify: bool,
    tls_ca_file: Path | None,
    tls_certificate_file: Path | None,
    tls_private_key_file: Path | None,
) -> Redis:
    return Redis(
        host=host,
        port=port,
        db=database,
        username=username,
        password=password,
        socket_connect_timeout=socket_connect_timeout_seconds,
        socket_timeout=socket_timeout_seconds,
        max_connections=max_connections,
        health_check_interval=health_check_interval_seconds,
        ssl=tls,
        ssl_cert_reqs="required" if tls_verify else "none",
        ssl_check_hostname=tls_verify,
        ssl_ca_certs=str(tls_ca_file) if tls_ca_file is not None else None,
        ssl_certfile=(str(tls_certificate_file) if tls_certificate_file is not None else None),
        ssl_keyfile=(str(tls_private_key_file) if tls_private_key_file is not None else None),
    )


class RedisClient:
    def __init__(self, transport: RedisTransport) -> None:
        self._transport = transport

    async def ping(self) -> bool:
        try:
            return await self._transport.ping()
        except RedisError as error:
            raise RedisClientError("Redis health check failed") from error

    async def get(self, key: str) -> str | None:
        try:
            value = await self._transport.get(key)
        except RedisError as error:
            raise RedisClientError(f"Failed to get Redis key {key}") from error
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode()
            except UnicodeDecodeError as error:
                raise RedisClientError(f"Redis key {key} is not UTF-8 text") from error
        raise RedisClientError(f"Unexpected Redis GET response: {type(value).__name__}")

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            stored = await self._transport.set(key, value, ex=ttl_seconds)
        except RedisError as error:
            raise RedisClientError(f"Failed to set Redis key {key}") from error
        if stored is True:
            return
        if isinstance(stored, (str, bytes)) and stored:
            return
        if stored is None or stored is False:
            raise RedisClientError(f"Redis did not store key {key}")
        raise RedisClientError(f"Unexpected Redis SET response: {type(stored).__name__}")

    async def delete(self, keys: tuple[str, ...]) -> None:
        try:
            deleted = await self._transport.delete(*keys)
        except RedisError as error:
            raise RedisClientError("Failed to delete Redis keys") from error
        if isinstance(deleted, bool) or not isinstance(deleted, int):
            raise RedisClientError(f"Unexpected Redis DELETE response: {type(deleted).__name__}")
