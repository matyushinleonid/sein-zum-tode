"""Async Redis client."""

from redis.asyncio import Redis

from sein_zum_tode.config import Settings


class RedisClient:
    """Owns and verifies a redis-py asyncio client."""

    def __init__(self, client: Redis) -> None:
        self.client = client

    @classmethod
    async def connect(cls, settings: Settings) -> RedisClient:
        client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_database,
            password=settings.redis_password.get_secret_value(),
            decode_responses=True,
        )
        instance = cls(client)
        try:
            await client.ping()
        except BaseException:
            await client.aclose()
            raise
        return instance

    async def close(self) -> None:
        await self.client.aclose()
