from pydantic import ValidationError

from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from sein_zum_tode.infrastructure.redis import RedisClient, RedisClientError
from sein_zum_tode.prediction.models import StoredDeathPrediction
from sein_zum_tode.prediction.ports import DeathPredictionRepository


class RedisDeathPredictionRepository(DeathPredictionRepository):
    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def load(self, key: str) -> StoredDeathPrediction | None:
        try:
            payload = await self._redis.get(key)
        except RedisClientError as error:
            raise PayloadRepositoryError(f"Failed to load death prediction at {key}") from error
        if payload is None:
            return None
        try:
            return StoredDeathPrediction.model_validate_json(payload)
        except ValidationError as error:
            raise InvalidStoredPayloadError(f"Invalid death prediction at {key}") from error

    async def store(
        self,
        key: str,
        prediction: StoredDeathPrediction,
        ttl_seconds: int,
    ) -> None:
        try:
            await self._redis.set(key, prediction.model_dump_json(), ttl_seconds)
        except RedisClientError as error:
            raise PayloadRepositoryError(f"Failed to store death prediction at {key}") from error
