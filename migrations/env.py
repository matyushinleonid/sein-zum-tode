import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from sein_zum_tode.infrastructure.postgres import create_postgres_engine
from sein_zum_tode.mortals.postgres import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def environment(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"{name} is required")
    return value


def run_migrations_offline() -> None:
    context.configure(
        url="postgresql+asyncpg://",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_postgres_engine(
        host=environment("POSTGRES_HOST", "localhost"),
        port=int(environment("POSTGRES_PORT", "5432")),
        database=environment("POSTGRES_DATABASE", "sein_zum_tode"),
        user=environment("POSTGRES_USER", "sein_zum_tode"),
        password=environment("POSTGRES_PASSWORD"),
        ssl=environment("POSTGRES_SSL", "false").lower() == "true",
        pgbouncer=environment("POSTGRES_PGBOUNCER", "false").lower() == "true",
    )
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
