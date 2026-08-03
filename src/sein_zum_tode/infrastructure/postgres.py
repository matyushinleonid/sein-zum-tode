from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import uuid4

from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import Executable
from sqlalchemy.sql.expression import text

from sein_zum_tode.infrastructure.tls import (
    PostgresTlsMode,
    create_postgres_ssl_context,
)


class PostgresClientError(Exception):
    pass


class PostgresMappingResult(Protocol):
    def one_or_none(self) -> Mapping[str, Any] | None: ...

    def all(self) -> Sequence[Mapping[str, Any]]: ...


class PostgresStatementResult(Protocol):
    def mappings(self) -> PostgresMappingResult: ...


class PostgresConnection(Protocol):
    async def execute(self, statement: Executable) -> PostgresStatementResult: ...


class PostgresEngine(Protocol):
    def begin(self) -> AbstractAsyncContextManager[PostgresConnection]: ...

    def connect(self) -> AbstractAsyncContextManager[PostgresConnection]: ...

    async def dispose(self) -> None: ...


class PostgresStatementClient(Protocol):
    async def execute(self, statement: Executable) -> None: ...

    async def fetch_one(self, statement: Executable) -> Mapping[str, Any] | None: ...

    async def fetch_all(self, statement: Executable) -> tuple[Mapping[str, Any], ...]: ...

    async def execute_returning_one(
        self,
        statement: Executable,
    ) -> Mapping[str, Any] | None: ...


def create_postgres_engine(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    tls_mode: PostgresTlsMode,
    tls_ca_file: Path | None,
    tls_certificate_file: Path | None,
    tls_private_key_file: Path | None,
    pgbouncer: bool,
    connect_timeout_seconds: float,
    pool_size: int,
    max_overflow: int,
    pool_timeout_seconds: float,
    pool_recycle_seconds: int,
) -> AsyncEngine:
    query = {"prepared_statement_cache_size": "0"} if pgbouncer else {}
    url = URL.create(
        drivername="postgresql+asyncpg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
        query=query,
    )
    options: dict[str, Any] = {
        "pool_recycle": pool_recycle_seconds,
    }
    connect_args: dict[str, Any] = {"timeout": connect_timeout_seconds}
    ssl_context = create_postgres_ssl_context(
        mode=tls_mode,
        ca_file=tls_ca_file,
        certificate_file=tls_certificate_file,
        private_key_file=tls_private_key_file,
    )
    if ssl_context is not None:
        connect_args["ssl"] = ssl_context
    if pgbouncer:
        options["poolclass"] = NullPool
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
    else:
        options.update(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout_seconds,
        )
    options["connect_args"] = connect_args
    return create_async_engine(url, **options)


class PostgresClient:
    def __init__(self, engine: AsyncEngine | PostgresEngine) -> None:
        self._engine = engine

    @classmethod
    def create(
        cls,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        tls_mode: PostgresTlsMode,
        tls_ca_file: Path | None,
        tls_certificate_file: Path | None,
        tls_private_key_file: Path | None,
        pgbouncer: bool,
        connect_timeout_seconds: float,
        pool_size: int,
        max_overflow: int,
        pool_timeout_seconds: float,
        pool_recycle_seconds: int,
    ) -> Self:
        return cls(
            create_postgres_engine(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                tls_mode=tls_mode,
                tls_ca_file=tls_ca_file,
                tls_certificate_file=tls_certificate_file,
                tls_private_key_file=tls_private_key_file,
                pgbouncer=pgbouncer,
                connect_timeout_seconds=connect_timeout_seconds,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout_seconds=pool_timeout_seconds,
                pool_recycle_seconds=pool_recycle_seconds,
            )
        )

    async def execute(self, statement: Executable) -> None:
        try:
            async with self._engine.begin() as connection:
                await connection.execute(statement)
        except SQLAlchemyError as error:
            raise PostgresClientError("PostgreSQL statement failed") from error

    async def ping(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise PostgresClientError("PostgreSQL health check failed") from error
        return True

    async def fetch_one(self, statement: Executable) -> Mapping[str, Any] | None:
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(statement)
                row = result.mappings().one_or_none()
                return {str(key): value for key, value in row.items()} if row is not None else None
        except SQLAlchemyError as error:
            raise PostgresClientError("PostgreSQL query failed") from error

    async def fetch_all(self, statement: Executable) -> tuple[Mapping[str, Any], ...]:
        try:
            async with self._engine.connect() as connection:
                rows = (await connection.execute(statement)).mappings().all()
                return tuple({str(key): value for key, value in row.items()} for row in rows)
        except SQLAlchemyError as error:
            raise PostgresClientError("PostgreSQL query failed") from error

    async def execute_returning_one(
        self,
        statement: Executable,
    ) -> Mapping[str, Any] | None:
        try:
            async with self._engine.begin() as connection:
                result = await connection.execute(statement)
                row = result.mappings().one_or_none()
                return {str(key): value for key, value in row.items()} if row is not None else None
        except SQLAlchemyError as error:
            raise PostgresClientError("PostgreSQL statement failed") from error

    async def close(self) -> None:
        await self._engine.dispose()
