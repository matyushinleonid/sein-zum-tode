from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, Self, cast

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from sein_zum_tode.infrastructure.postgres import (
    PostgresClient,
    PostgresClientError,
    PostgresConnection,
    PostgresEngine,
    PostgresMappingResult,
    PostgresStatementResult,
)

pytestmark = pytest.mark.fast


def result_or_raise[T](value: T | BaseException) -> T:
    if isinstance(value, BaseException):
        raise value
    return value


class ResultDouble(PostgresStatementResult, PostgresMappingResult):
    def __init__(self, row: Mapping[str, Any] | None) -> None:
        self.row = row

    def mappings(self) -> Self:
        return self

    def one_or_none(self) -> Mapping[str, Any] | None:
        return self.row


class ConnectionDouble(PostgresConnection):
    def __init__(
        self,
        outcomes: list[PostgresStatementResult | BaseException],
        events: list[tuple[object, ...]],
    ) -> None:
        self.outcomes = outcomes
        self.events = events

    async def execute(self, statement: object) -> PostgresStatementResult:
        self.events.append(("execute", str(statement)))
        return result_or_raise(self.outcomes.pop(0))


class ConnectionContext(AbstractAsyncContextManager[PostgresConnection]):
    def __init__(self, connection: ConnectionDouble) -> None:
        self.connection = connection

    async def __aenter__(self) -> PostgresConnection:
        return self.connection

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class EngineDouble(PostgresEngine):
    def __init__(
        self,
        outcomes: list[PostgresStatementResult | BaseException],
    ) -> None:
        self.events: list[tuple[object, ...]] = []
        self.connection = ConnectionDouble(outcomes, self.events)

    def client(self) -> PostgresClient:
        return PostgresClient(self)

    def begin(self) -> AbstractAsyncContextManager[PostgresConnection]:
        self.events.append(("begin",))
        return ConnectionContext(self.connection)

    def connect(self) -> AbstractAsyncContextManager[PostgresConnection]:
        self.events.append(("connect",))
        return ConnectionContext(self.connection)

    async def dispose(self) -> None:
        self.events.append(("dispose",))


class EngineFactoryDouble:
    def __init__(self, engine: EngineDouble) -> None:
        self.engine = engine
        self.url: URL | None = None
        self.options: dict[str, object] = {}

    def __call__(self, url: URL, **options: object) -> EngineDouble:
        self.url = url
        self.options = options
        return self.engine


def test_creates_an_asyncpg_engine_safe_for_tls_pgbouncer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = EngineDouble(outcomes=[])
    factory = EngineFactoryDouble(engine)
    monkeypatch.setattr(
        "sein_zum_tode.infrastructure.postgres.create_async_engine",
        factory,
    )

    actual = PostgresClient.create(
        host="postgres-quasar.internal",
        port=3121,
        database="mortals_3127",
        user="mortal_3137",
        password="private-3163",
        ssl=True,
        pgbouncer=True,
    )

    connect_args = cast(dict[str, object], factory.options["connect_args"])
    name_factory = cast(Any, connect_args["prepared_statement_name_func"])
    assert (
        actual._engine is engine,
        factory.url.render_as_string(hide_password=False) if factory.url else None,
        cast(type[Any], factory.options["poolclass"]).__name__,
        connect_args["ssl"],
        str(name_factory()).startswith("__asyncpg_"),
    ) == (
        True,
        "postgresql+asyncpg://mortal_3137:private-3163@postgres-quasar.internal:3121/"
        "mortals_3127?prepared_statement_cache_size=0",
        "NullPool",
        True,
        True,
    ), "PostgreSQL engine lost credentials or PgBouncer-safe connection options"


async def test_executes_writes_and_reads_one_mapping() -> None:
    row = {"id": 3167, "locale": "en"}
    engine = EngineDouble(
        outcomes=[
            ResultDouble(None),
            ResultDouble(row),
        ]
    )
    client = engine.client()

    await client.execute(text("UPDATE mortals SET locale = 'en'"))
    actual = await client.fetch_one(text("SELECT id, locale FROM mortals"))
    await client.close()

    assert (
        actual,
        engine.events,
    ) == (
        row,
        [
            ("begin",),
            ("execute", "UPDATE mortals SET locale = 'en'"),
            ("connect",),
            ("execute", "SELECT id, locale FROM mortals"),
            ("dispose",),
        ],
    ), "PostgresClient selected the wrong transaction mode or changed the query result"


async def test_executes_a_returning_statement_inside_a_transaction() -> None:
    row = {"id": 3169, "llm_requests_remaining": 49}
    engine = EngineDouble(outcomes=[ResultDouble(row)])

    actual = await engine.client().execute_returning_one(
        text("UPDATE mortals SET llm_requests_remaining = 49 RETURNING *")
    )

    assert (
        actual,
        engine.events,
    ) == (
        row,
        [
            ("begin",),
            (
                "execute",
                "UPDATE mortals SET llm_requests_remaining = 49 RETURNING *",
            ),
        ],
    )


@pytest.mark.parametrize(
    ("operation", "expected_message"),
    [
        ("execute", "PostgreSQL statement failed"),
        ("fetch_one", "PostgreSQL query failed"),
        ("execute_returning_one", "PostgreSQL statement failed"),
    ],
)
async def test_translates_sqlalchemy_failures(
    operation: str,
    expected_message: str,
) -> None:
    engine = EngineDouble(outcomes=[SQLAlchemyError("collapsed orbit 3169")])
    client = engine.client()

    with pytest.raises(PostgresClientError, match=expected_message):
        if operation == "execute":
            await client.execute(text("DELETE FROM mortals"))
        elif operation == "fetch_one":
            await client.fetch_one(text("SELECT id FROM mortals"))
        else:
            await client.execute_returning_one(text("UPDATE mortals RETURNING id"))
