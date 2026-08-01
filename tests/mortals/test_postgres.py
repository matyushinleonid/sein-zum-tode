from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest
from sqlalchemy.sql import ClauseElement, Executable

from sein_zum_tode.infrastructure.postgres import (
    PostgresClientError,
)
from sein_zum_tode.mortals.errors import MortalQuotaExhaustedError, MortalRepositoryError
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.mortals.postgres import PostgresMortalRepository

pytestmark = pytest.mark.fast


def result_or_raise[T](value: T | BaseException) -> T:
    if isinstance(value, BaseException):
        raise value
    return value


class PostgresStatementClientDouble:
    def __init__(
        self,
        *,
        execute_outcomes: list[BaseException | None] | None = None,
        fetch_outcomes: list[Mapping[str, Any] | BaseException | None] | None = None,
        returning_outcomes: list[Mapping[str, Any] | BaseException | None] | None = None,
    ) -> None:
        self.execute_outcomes = list(execute_outcomes or [])
        self.fetch_outcomes = list(fetch_outcomes or [])
        self.returning_outcomes = list(returning_outcomes or [])
        self.events: list[tuple[str, ClauseElement]] = []

    def record(self, operation: str, statement: Executable) -> None:
        assert isinstance(statement, ClauseElement)
        self.events.append((operation, statement))

    def repository(self) -> PostgresMortalRepository:
        return PostgresMortalRepository(self)

    async def execute(self, statement: Executable) -> None:
        self.record("execute", statement)
        outcome = self.execute_outcomes.pop(0) if self.execute_outcomes else None
        result_or_raise(outcome)

    async def fetch_one(
        self,
        statement: Executable,
    ) -> Mapping[str, Any] | None:
        self.record("fetch_one", statement)
        outcome = self.fetch_outcomes.pop(0)
        return result_or_raise(outcome)

    async def execute_returning_one(
        self,
        statement: Executable,
    ) -> Mapping[str, Any] | None:
        self.record("execute_returning_one", statement)
        outcome = self.returning_outcomes.pop(0)
        return result_or_raise(outcome)


def mortal_row(
    *,
    mortal_id: int,
    locale: str | None = None,
    death_date: date | None = None,
    notification_cron: str | None = "0 9 * * *",
    llm_requests_remaining: int = 50,
) -> Mapping[str, Any]:
    return {
        "id": mortal_id,
        "locale": locale,
        "timezone": "Europe/Moscow",
        "notification_cron": notification_cron,
        "death_date": death_date,
        "llm_requests_remaining": llm_requests_remaining,
    }


def parameters(statement: ClauseElement) -> dict[str, object]:
    parameters = statement.compile().params
    assert parameters is not None
    return {str(key): value for key, value in parameters.items()}


async def test_registers_a_mortal_idempotently_with_fixed_defaults() -> None:
    client = PostgresStatementClientDouble(fetch_outcomes=[mortal_row(mortal_id=320_009)])

    actual = await client.repository().ensure(320_009)

    insert_statement = client.events[0][1]
    assert (
        actual,
        parameters(insert_statement),
        "ON CONFLICT" in str(insert_statement),
        client.events[1][0],
    ) == (
        Mortal(id=320_009),
        {
            "id": 320_009,
            "locale": None,
            "timezone": "Europe/Moscow",
            "notification_cron": "0 9 * * *",
            "death_date": None,
            "llm_requests_remaining": 50,
        },
        True,
        "fetch_one",
    ), "Mortal registration lost defaults or stopped being idempotent"


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (mortal_row(mortal_id=320_011), Mortal(id=320_011)),
        (None, None),
    ],
)
async def test_loads_an_existing_or_absent_mortal(
    row: Mapping[str, Any] | None,
    expected: Mortal | None,
) -> None:
    client = PostgresStatementClientDouble(fetch_outcomes=[row])

    actual = await client.repository().get(320_011)

    assert actual == expected, "Mortal lookup changed an existing row or fabricated one"


async def test_sets_the_configured_death_date_with_an_upsert() -> None:
    death_date = date(2100, 1, 1)
    client = PostgresStatementClientDouble(
        fetch_outcomes=[
            mortal_row(
                mortal_id=320_017,
                death_date=death_date,
            )
        ]
    )

    actual = await client.repository().set_death_date(320_017, death_date)

    statement = client.events[0][1]
    assert (
        actual.death_date,
        parameters(statement)["death_date"],
        "DO UPDATE" in str(statement),
    ) == (
        death_date,
        death_date,
        True,
    ), "death date activation did not use an idempotent PostgreSQL upsert"


async def test_resets_all_preferences_and_death_date_after_unblock() -> None:
    client = PostgresStatementClientDouble(fetch_outcomes=[mortal_row(mortal_id=320_019)])

    actual = await client.repository().reset(320_019)

    statement = client.events[0][1]
    assert (
        actual,
        parameters(statement),
        "DO UPDATE" in str(statement),
    ) == (
        Mortal(id=320_019),
        {
            "id": 320_019,
            "locale": None,
            "timezone": "Europe/Moscow",
            "notification_cron": "0 9 * * *",
            "death_date": None,
            "llm_requests_remaining": 50,
            "param_1": None,
            "param_2": "Europe/Moscow",
            "param_3": "0 9 * * *",
            "param_4": None,
            "param_5": 50,
        },
        True,
    ), "unblock reset retained old Mortal preferences or death date"


async def test_deletes_a_mortal_idempotently() -> None:
    client = PostgresStatementClientDouble()

    await client.repository().delete(320_023)

    assert (
        client.events[0][0],
        "DELETE FROM mortals" in str(client.events[0][1]),
        parameters(client.events[0][1]),
    ) == (
        "execute",
        True,
        {"id_1": 320_023},
    ), "Mortal deletion targeted the wrong table or id"


async def test_updates_notification_cron_and_reads_the_mortal_back() -> None:
    client = PostgresStatementClientDouble(
        fetch_outcomes=[
            mortal_row(
                mortal_id=320_021,
                notification_cron="0 9 1 * *",
            )
        ]
    )

    actual = await client.repository().set_notification_cron(
        320_021,
        "0 9 1 * *",
    )

    assert (
        actual.notification_cron,
        "UPDATE mortals" in str(client.events[0][1]),
    ) == (
        "0 9 1 * *",
        True,
    )


async def test_updates_locale_and_reads_the_mortal_back() -> None:
    client = PostgresStatementClientDouble(
        fetch_outcomes=[mortal_row(mortal_id=320_022, locale="ru")]
    )

    actual = await client.repository().set_locale(320_022, "ru")

    assert (
        actual.locale,
        "UPDATE mortals" in str(client.events[0][1]),
        parameters(client.events[0][1]),
    ) == (
        "ru",
        True,
        {"locale": "ru", "id_1": 320_022},
    ), "locale selection did not target the requested Mortal"


async def test_consumes_one_llm_request_with_a_transactional_ledger() -> None:
    row = mortal_row(mortal_id=320_025, llm_requests_remaining=49)
    client = PostgresStatementClientDouble(returning_outcomes=[row])

    actual = await client.repository().consume_llm_request(
        320_025,
        "request-3209",
    )

    statement = client.events[0][1]
    assert (
        actual.llm_requests_remaining,
        client.events[0][0],
        "llm_request_consumptions" in str(statement),
        "RETURNING" in str(statement),
    ) == (
        49,
        "execute_returning_one",
        True,
        True,
    ), "quota consumption was not atomic or did not use the idempotency ledger"


async def test_replaying_a_consumed_request_does_not_decrement_again() -> None:
    client = PostgresStatementClientDouble(
        returning_outcomes=[None],
        fetch_outcomes=[
            mortal_row(mortal_id=320_031, llm_requests_remaining=49),
            {"request_id": "request-3217"},
        ],
    )

    actual = await client.repository().consume_llm_request(
        320_031,
        "request-3217",
    )

    assert actual.llm_requests_remaining == 49


async def test_rejects_a_new_request_after_quota_exhaustion() -> None:
    client = PostgresStatementClientDouble(
        returning_outcomes=[None],
        fetch_outcomes=[
            mortal_row(mortal_id=320_033, llm_requests_remaining=0),
            None,
        ],
    )

    with pytest.raises(MortalQuotaExhaustedError):
        await client.repository().consume_llm_request(
            320_033,
            "request-3221",
        )


@pytest.mark.parametrize(
    "operation",
    [
        "ensure",
        "get",
        "reset",
        "set_death_date",
        "set_notification_cron",
        "set_locale",
        "consume_llm_request",
        "delete",
    ],
)
async def test_translates_postgres_failures(operation: str) -> None:
    failure = PostgresClientError(f"{operation} collapsed 3203")
    client = PostgresStatementClientDouble(
        execute_outcomes=[failure],
        fetch_outcomes=[failure],
        returning_outcomes=[failure],
    )
    repository = client.repository()

    with pytest.raises(MortalRepositoryError):
        if operation == "ensure":
            await repository.ensure(320_027)
        elif operation == "get":
            await repository.get(320_027)
        elif operation == "reset":
            await repository.reset(320_027)
        elif operation == "set_death_date":
            await repository.set_death_date(320_027, date(2100, 1, 1))
        elif operation == "set_notification_cron":
            await repository.set_notification_cron(320_027, None)
        elif operation == "set_locale":
            await repository.set_locale(320_027, "ru")
        elif operation == "consume_llm_request":
            await repository.consume_llm_request(320_027, "request-32027")
        else:
            await repository.delete(320_027)


@pytest.mark.parametrize(
    "operation",
    ["ensure", "reset", "set_death_date", "set_notification_cron", "set_locale"],
)
async def test_rejects_a_write_that_cannot_be_read_back(operation: str) -> None:
    client = PostgresStatementClientDouble(fetch_outcomes=[None])
    repository = client.repository()

    with pytest.raises(MortalRepositoryError, match="was not found"):
        if operation == "ensure":
            await repository.ensure(320_039)
        elif operation == "reset":
            await repository.reset(320_039)
        elif operation == "set_death_date":
            await repository.set_death_date(320_039, date(2100, 1, 1))
        elif operation == "set_notification_cron":
            await repository.set_notification_cron(320_039, None)
        else:
            await repository.set_locale(320_039, "ru")


async def test_rejects_quota_consumption_for_a_missing_mortal() -> None:
    client = PostgresStatementClientDouble(
        returning_outcomes=[None],
        fetch_outcomes=[None, None],
    )

    with pytest.raises(MortalRepositoryError, match="was not found"):
        await client.repository().consume_llm_request(
            320_041,
            "request-32041",
        )
