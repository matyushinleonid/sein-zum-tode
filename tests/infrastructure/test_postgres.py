from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import ClauseElement

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
    def __init__(
        self,
        row: Mapping[str, Any] | None,
        rows: tuple[Mapping[str, Any], ...] = (),
    ) -> None:
        self.row = row
        self.rows = rows

    def mappings(self) -> Self:
        return self

    def one_or_none(self) -> Mapping[str, Any] | None:
        return self.row

    def all(self) -> tuple[Mapping[str, Any], ...]:
        return self.rows


class ConnectionDouble(PostgresConnection):
    def __init__(
        self,
        outcomes: list[PostgresStatementResult | BaseException],
        events: list[tuple[object, ...]],
    ) -> None:
        self.outcomes = outcomes
        self.events = events

    async def execute(self, statement: object) -> PostgresStatementResult:
        assert isinstance(statement, ClauseElement)
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
    ssl_context = object()
    tls_options: list[dict[str, object]] = []

    def create_ssl_context(**options: object) -> object:
        tls_options.append(options)
        return ssl_context

    monkeypatch.setattr(
        "sein_zum_tode.infrastructure.postgres.create_async_engine",
        factory,
    )
    monkeypatch.setattr(
        "sein_zum_tode.infrastructure.postgres.create_postgres_ssl_context",
        create_ssl_context,
    )

    actual = PostgresClient.create(
        host="postgres-quasar.internal",
        port=3121,
        database="mortals_3127",
        user="mortal_3137",
        password="private-3163",
        tls_mode="verify-full",
        tls_ca_file=Path("/certificates/quasar-ca-3167.pem"),
        tls_certificate_file=Path("/certificates/mortal-3169.pem"),
        tls_private_key_file=Path("/certificates/mortal-3181.key"),
        pgbouncer=True,
        connect_timeout_seconds=7.3,
        pool_size=17,
        max_overflow=19,
        pool_timeout_seconds=23.0,
        pool_recycle_seconds=3187,
    )

    connect_args = cast(dict[str, object], factory.options["connect_args"])
    name_factory = cast(Any, connect_args["prepared_statement_name_func"])
    assert (
        actual._engine is engine,
        factory.url.render_as_string(hide_password=False) if factory.url else None,
        cast(type[Any], factory.options["poolclass"]).__name__,
        connect_args["ssl"] is ssl_context,
        connect_args["timeout"],
        factory.options["pool_recycle"],
        tls_options,
        str(name_factory()).startswith("__asyncpg_"),
    ) == (
        True,
        "postgresql+asyncpg://mortal_3137:private-3163@postgres-quasar.internal:3121/"
        "mortals_3127?prepared_statement_cache_size=0",
        "NullPool",
        True,
        7.3,
        3187,
        [
            {
                "mode": "verify-full",
                "ca_file": Path("/certificates/quasar-ca-3167.pem"),
                "certificate_file": Path("/certificates/mortal-3169.pem"),
                "private_key_file": Path("/certificates/mortal-3181.key"),
            }
        ],
        True,
    ), "PostgreSQL engine lost credentials or PgBouncer-safe connection options"


def test_creates_a_bounded_connection_pool_without_pgbouncer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = EngineDouble(outcomes=[])
    factory = EngineFactoryDouble(engine)
    monkeypatch.setattr(
        "sein_zum_tode.infrastructure.postgres.create_async_engine",
        factory,
    )
    monkeypatch.setattr(
        "sein_zum_tode.infrastructure.postgres.create_postgres_ssl_context",
        lambda **_: None,
    )

    PostgresClient.create(
        host="postgres-pool.internal",
        port=3191,
        database="mortals_3203",
        user="mortal_3209",
        password="private-3217",
        tls_mode="disable",
        tls_ca_file=None,
        tls_certificate_file=None,
        tls_private_key_file=None,
        pgbouncer=False,
        connect_timeout_seconds=11.0,
        pool_size=13,
        max_overflow=17,
        pool_timeout_seconds=19.0,
        pool_recycle_seconds=3221,
    )

    assert factory.options == {
        "pool_recycle": 3221,
        "pool_size": 13,
        "max_overflow": 17,
        "pool_timeout": 19.0,
        "connect_args": {"timeout": 11.0},
    }, "non-PgBouncer PostgreSQL connections ignored pool limits"


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


async def test_reads_all_query_mappings() -> None:
    rows = (
        {"id": 3173, "locale": "en"},
        {"id": 3181, "locale": "en"},
    )
    engine = EngineDouble(outcomes=[ResultDouble(None, rows)])

    actual = await engine.client().fetch_all(text("SELECT id, locale FROM mortals"))

    assert actual == rows, "PostgresClient discarded or changed rows from a paged query"


async def test_checks_postgres_connectivity_with_a_constant_query() -> None:
    engine = EngineDouble(outcomes=[ResultDouble(None)])

    actual = await engine.client().ping()

    assert (actual, engine.events) == (
        True,
        [("connect",), ("execute", "SELECT 1")],
    ), "PostgreSQL health check opened a transaction or queried application data"


@pytest.mark.parametrize(
    ("operation", "expected_message"),
    [
        ("execute", "PostgreSQL statement failed"),
        ("fetch_one", "PostgreSQL query failed"),
        ("fetch_all", "PostgreSQL query failed"),
        ("execute_returning_one", "PostgreSQL statement failed"),
        ("ping", "PostgreSQL health check failed"),
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
        elif operation == "fetch_all":
            await client.fetch_all(text("SELECT id FROM mortals"))
        elif operation == "execute_returning_one":
            await client.execute_returning_one(text("UPDATE mortals RETURNING id"))
        else:
            await client.ping()
