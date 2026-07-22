"""Async SQLAlchemy client."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from sein_zum_tode.config import Settings


class DatabaseClient:
    """Owns the application's SQLAlchemy async engine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @classmethod
    async def connect(cls, settings: Settings) -> DatabaseClient:
        connect_args: dict[str, object] = {"ssl": settings.postgres_ssl}
        engine_options: dict[str, object] = {
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        if settings.postgres_pgbouncer:
            # PgBouncer already owns connection pooling. A second pool in the
            # process can hold server connections and prepared statements in a
            # way that is unsafe for transaction-pooling mode.
            engine_options["poolclass"] = NullPool
            connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"

        engine = create_async_engine(settings.database_url, **engine_options)
        client = cls(engine)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except BaseException:
            await engine.dispose()
            raise
        return client

    async def close(self) -> None:
        await self.engine.dispose()
