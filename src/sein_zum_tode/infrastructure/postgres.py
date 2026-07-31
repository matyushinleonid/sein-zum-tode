from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, Self
from uuid import uuid4

from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import Executable


class PostgresClientError(Exception):
    pass


class PostgresMappingResult(Protocol):
    def one_or_none(self) -> Mapping[str, Any] | None: ...


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
    ssl: bool,
    pgbouncer: bool,
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
    options: dict[str, Any] = {}
    connect_args: dict[str, Any] = {}
    if ssl:
        connect_args["ssl"] = True
    if pgbouncer:
        options["poolclass"] = NullPool
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
    if connect_args:
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
        ssl: bool,
        pgbouncer: bool,
    ) -> Self:
        return cls(
            create_postgres_engine(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                ssl=ssl,
                pgbouncer=pgbouncer,
            )
        )

    async def execute(self, statement: Executable) -> None:
        try:
            async with self._engine.begin() as connection:
                await connection.execute(statement)
        except SQLAlchemyError as error:
            raise PostgresClientError("PostgreSQL statement failed") from error

    async def fetch_one(self, statement: Executable) -> Mapping[str, Any] | None:
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(statement)
                row = result.mappings().one_or_none()
                return dict(row) if row is not None else None
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
                return dict(row) if row is not None else None
        except SQLAlchemyError as error:
            raise PostgresClientError("PostgreSQL statement failed") from error

    async def close(self) -> None:
        await self._engine.dispose()
