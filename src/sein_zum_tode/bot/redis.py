from aiogram.types import Update
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.ports import (
    TelegramPayloadCleaner,
    TelegramResponseReader,
    TelegramResponseStore,
    TelegramUpdateReader,
)


class RedisTelegramPayloadRepository(
    TelegramUpdateReader,
    TelegramResponseStore,
    TelegramResponseReader,
    TelegramPayloadCleaner,
):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def load_update(self, key: str) -> Update | None:
        payload = await self._read(key)
        if payload is None:
            return None
        try:
            return Update.model_validate_json(payload)
        except ValidationError as error:
            raise InvalidStoredPayloadError(f"Invalid Telegram update at {key}") from error

    async def store_response(
        self,
        key: str,
        response: TelegramResponse,
        ttl_seconds: int,
    ) -> None:
        try:
            stored = await self._redis.set(
                key,
                response.model_dump_json(),
                ex=ttl_seconds,
            )
        except RedisError as error:
            raise PayloadRepositoryError(f"Failed to store Telegram response at {key}") from error
        if not stored:
            raise PayloadRepositoryError(f"Redis did not store Telegram response at {key}")

    async def load_response(self, key: str) -> TelegramResponse | None:
        payload = await self._read(key)
        if payload is None:
            return None
        try:
            return TelegramResponse.model_validate_json(payload)
        except ValidationError as error:
            raise InvalidStoredPayloadError(f"Invalid Telegram response at {key}") from error

    async def delete(self, keys: tuple[str, ...]) -> None:
        try:
            await self._redis.delete(*keys)
        except RedisError as error:
            raise PayloadRepositoryError("Failed to delete Telegram payloads") from error

    async def _read(self, key: str) -> str | bytes | None:
        try:
            payload = await self._redis.get(key)
        except RedisError as error:
            raise PayloadRepositoryError(f"Failed to load Telegram payload at {key}") from error
        if payload is None or isinstance(payload, (str, bytes)):
            return payload
        raise TypeError(f"Unexpected Redis GET response: {type(payload).__name__}")
