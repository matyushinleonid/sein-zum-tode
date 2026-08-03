import asyncio
import os
from logging.config import fileConfig
from pathlib import Path
from typing import cast

from alembic import context
from sqlalchemy import Connection

from sein_zum_tode.infrastructure.postgres import create_postgres_engine
from sein_zum_tode.infrastructure.tls import PostgresTlsMode
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


def optional_path(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value) if value else None


def postgres_tls_mode() -> PostgresTlsMode:
    value = environment("POSTGRES_TLS_MODE", "disable")
    if value not in {"disable", "require", "verify-ca", "verify-full"}:
        raise RuntimeError(f"Unsupported POSTGRES_TLS_MODE: {value}")
    return cast(PostgresTlsMode, value)


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
        tls_mode=postgres_tls_mode(),
        tls_ca_file=optional_path("POSTGRES_TLS_CA_FILE"),
        tls_certificate_file=optional_path("POSTGRES_TLS_CERTIFICATE_FILE"),
        tls_private_key_file=optional_path("POSTGRES_TLS_PRIVATE_KEY_FILE"),
        pgbouncer=environment("POSTGRES_PGBOUNCER", "false").lower() == "true",
        connect_timeout_seconds=float(environment("POSTGRES_CONNECT_TIMEOUT_SECONDS", "10")),
        pool_size=int(environment("POSTGRES_POOL_SIZE", "5")),
        max_overflow=int(environment("POSTGRES_MAX_OVERFLOW", "10")),
        pool_timeout_seconds=float(environment("POSTGRES_POOL_TIMEOUT_SECONDS", "30")),
        pool_recycle_seconds=int(environment("POSTGRES_POOL_RECYCLE_SECONDS", "-1")),
    )
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
