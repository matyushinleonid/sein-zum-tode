from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from sein_zum_tode.bot.conversation.models import ConversationState
from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError


class RedisConversationStateRepository:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def load_conversation(self, key: str) -> ConversationState | None:
        try:
            payload = await self._redis.get(key)
        except RedisError as error:
            raise PayloadRepositoryError(
                f"Failed to load Telegram conversation at {key}"
            ) from error
        if payload is None:
            return None
        if not isinstance(payload, (str, bytes)):
            raise TypeError(f"Unexpected Redis GET response: {type(payload).__name__}")
        try:
            return ConversationState.model_validate_json(payload)
        except ValidationError as error:
            raise InvalidStoredPayloadError(f"Invalid Telegram conversation at {key}") from error

    async def store_conversation(
        self,
        key: str,
        state: ConversationState,
        ttl_seconds: int,
    ) -> None:
        try:
            stored = await self._redis.set(
                key,
                state.model_dump_json(),
                ex=ttl_seconds,
            )
        except RedisError as error:
            raise PayloadRepositoryError(
                f"Failed to store Telegram conversation at {key}"
            ) from error
        if not stored:
            raise PayloadRepositoryError(f"Redis did not store Telegram conversation at {key}")
