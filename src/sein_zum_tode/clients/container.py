"""Lifecycle container for infrastructure clients."""

from dataclasses import dataclass

from sein_zum_tode.clients.database import DatabaseClient
from sein_zum_tode.clients.redis import RedisClient
from sein_zum_tode.clients.temporal import TemporalClient
from sein_zum_tode.config import Settings


@dataclass(slots=True)
class ApplicationClients:
    """Connected clients passed explicitly to future application components."""

    database: DatabaseClient
    redis: RedisClient
    temporal: TemporalClient

    @classmethod
    async def connect(cls, settings: Settings) -> ApplicationClients:
        database = await DatabaseClient.connect(settings)
        try:
            redis = await RedisClient.connect(settings)
            temporal = await TemporalClient.connect(settings)
        except BaseException:
            await database.close()
            if "redis" in locals():
                await redis.close()
            raise
        return cls(database=database, redis=redis, temporal=temporal)

    async def close(self) -> None:
        # Temporal's high-level Client has no public close method. Its core
        # runtime is process-scoped and is released when the process exits.
        await self.redis.close()
        await self.database.close()
