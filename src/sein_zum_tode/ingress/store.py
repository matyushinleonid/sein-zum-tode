from aiogram.types import Update

from sein_zum_tode.infrastructure.redis import RedisClient, RedisClientError
from sein_zum_tode.ingress.errors import UpdateStoreError
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.ports import UpdateUserResolver


class RedisUpdateStore:
    def __init__(
        self,
        redis: RedisClient,
        user_resolver: UpdateUserResolver,
        bot_id: int,
        ttl_seconds: int,
        key_prefix: str = "telegram:updates",
    ) -> None:
        self._redis = redis
        self._user_resolver = user_resolver
        self._bot_id = bot_id
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix

    async def store(self, update: Update) -> StoredUpdate:
        key = f"{self._key_prefix}:{self._bot_id}:{update.update_id}"
        payload = update.model_dump_json(by_alias=True, exclude_none=True)
        try:
            await self._redis.set(key, payload, self._ttl_seconds)
        except RedisClientError as error:
            raise UpdateStoreError(f"Failed to store Telegram update {update.update_id}") from error
        return StoredUpdate(
            update_id=update.update_id,
            key=key,
            ttl_seconds=self._ttl_seconds,
            user_id=self._user_resolver.resolve(update),
        )
