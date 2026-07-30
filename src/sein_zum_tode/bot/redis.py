from aiogram.types import Update
from pydantic import ValidationError

from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.ports import (
    TelegramPayloadCleaner,
    TelegramResponseReader,
    TelegramResponseStore,
    TelegramUpdateReader,
)
from sein_zum_tode.infrastructure.redis import RedisClient, RedisClientError


class RedisTelegramPayloadRepository(
    TelegramUpdateReader,
    TelegramResponseStore,
    TelegramResponseReader,
    TelegramPayloadCleaner,
):
    def __init__(self, redis: RedisClient) -> None:
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
            await self._redis.set(
                key,
                response.model_dump_json(),
                ttl_seconds,
            )
        except RedisClientError as error:
            raise PayloadRepositoryError(f"Failed to store Telegram response at {key}") from error

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
            await self._redis.delete(keys)
        except RedisClientError as error:
            raise PayloadRepositoryError("Failed to delete Telegram payloads") from error

    async def _read(self, key: str) -> str | None:
        try:
            return await self._redis.get(key)
        except RedisClientError as error:
            raise PayloadRepositoryError(f"Failed to load Telegram payload at {key}") from error
