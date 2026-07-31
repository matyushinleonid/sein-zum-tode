from pydantic import ValidationError

from sein_zum_tode.bot.conversation.models import ConversationState
from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from sein_zum_tode.infrastructure.redis import RedisClient, RedisClientError


class RedisConversationStateRepository:
    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def load_conversation(self, key: str) -> ConversationState | None:
        try:
            payload = await self._redis.get(key)
        except RedisClientError as error:
            raise PayloadRepositoryError(
                f"Failed to load Telegram conversation at {key}"
            ) from error
        if payload is None:
            return None
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
            await self._redis.set(
                key,
                state.model_dump_json(),
                ttl_seconds,
            )
        except RedisClientError as error:
            raise PayloadRepositoryError(
                f"Failed to store Telegram conversation at {key}"
            ) from error
