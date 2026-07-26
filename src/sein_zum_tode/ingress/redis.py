from redis.asyncio import Redis


class RedisKeyValueClient:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
    ) -> bool | str | bytes | None:
        response = await self._redis.set(name, value, ex=ex)
        if response is None or isinstance(response, (bool, str, bytes)):
            return response
        raise TypeError(f"Unexpected Redis SET response: {type(response).__name__}")
