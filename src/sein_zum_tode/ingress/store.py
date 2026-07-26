from aiogram.types import Update
from redis.exceptions import RedisError

from sein_zum_tode.ingress.errors import UpdateStoreError
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.ports import KeyValueClient


class RedisUpdateStore:
    def __init__(
        self,
        redis: KeyValueClient,
        bot_id: int,
        ttl_seconds: int,
        key_prefix: str = "telegram:updates",
    ) -> None:
        self._redis = redis
        self._bot_id = bot_id
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix

    async def store(self, update: Update) -> StoredUpdate:
        key = f"{self._key_prefix}:{self._bot_id}:{update.update_id}"
        payload = update.model_dump_json(by_alias=True, exclude_none=True)
        try:
            stored = await self._redis.set(key, payload, ex=self._ttl_seconds)
        except RedisError as error:
            raise UpdateStoreError(f"Failed to store Telegram update {update.update_id}") from error
        if not stored:
            raise UpdateStoreError(f"Redis did not store Telegram update {update.update_id}")
        return StoredUpdate(
            update_id=update.update_id,
            key=key,
            ttl_seconds=self._ttl_seconds,
        )
