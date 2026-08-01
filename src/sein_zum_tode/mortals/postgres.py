from datetime import date

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    exists,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from sein_zum_tode.infrastructure.postgres import (
    PostgresClientError,
    PostgresStatementClient,
)
from sein_zum_tode.mortals.errors import MortalQuotaExhaustedError, MortalRepositoryError
from sein_zum_tode.mortals.models import (
    DEFAULT_LLM_REQUESTS_REMAINING,
    DEFAULT_MORTAL_NOTIFICATION_CRON,
    DEFAULT_MORTAL_TIMEZONE,
    Mortal,
)
from sein_zum_tode.mortals.ports import MortalRepository

metadata = MetaData()

mortal_id_column: Column[int] = Column(
    "id",
    BigInteger,
    primary_key=True,
    autoincrement=False,
)
mortal_locale_column: Column[str] = Column(
    "locale",
    String(16),
    nullable=True,
)
mortal_timezone_column: Column[str] = Column(
    "timezone",
    String(64),
    nullable=False,
    server_default=text("'Europe/Moscow'"),
)
mortal_notification_cron_column: Column[str] = Column(
    "notification_cron",
    String(128),
    nullable=True,
    server_default=text("'0 9 * * *'"),
)
mortal_death_date_column: Column[date] = Column(
    "death_date",
    Date,
    nullable=True,
)
mortal_llm_requests_remaining_column: Column[int] = Column(
    "llm_requests_remaining",
    Integer,
    nullable=False,
    server_default=text("50"),
)

mortals = Table(
    "mortals",
    metadata,
    mortal_id_column,
    mortal_locale_column,
    mortal_timezone_column,
    mortal_notification_cron_column,
    mortal_death_date_column,
    mortal_llm_requests_remaining_column,
)

llm_request_id_column: Column[str] = Column(
    "request_id",
    String(128),
    primary_key=True,
)
llm_request_mortal_id_column: Column[int] = Column(
    "mortal_id",
    BigInteger,
    ForeignKey("mortals.id", ondelete="CASCADE"),
    nullable=False,
)

llm_request_consumptions = Table(
    "llm_request_consumptions",
    metadata,
    llm_request_id_column,
    llm_request_mortal_id_column,
)


class PostgresMortalRepository(MortalRepository):
    def __init__(self, postgres: PostgresStatementClient) -> None:
        self._postgres = postgres

    async def ensure(self, mortal_id: int) -> Mortal:
        statement = (
            insert(mortals)
            .values(
                id=mortal_id,
                locale=None,
                timezone=DEFAULT_MORTAL_TIMEZONE,
                notification_cron=DEFAULT_MORTAL_NOTIFICATION_CRON,
                death_date=None,
                llm_requests_remaining=DEFAULT_LLM_REQUESTS_REMAINING,
            )
            .on_conflict_do_nothing(index_elements=[mortal_id_column])
        )
        try:
            await self._postgres.execute(statement)
            mortal = await self._get(mortal_id)
        except PostgresClientError as error:
            raise MortalRepositoryError(f"Failed to register Mortal {mortal_id}") from error
        if mortal is None:
            raise MortalRepositoryError(f"Registered Mortal {mortal_id} was not found")
        return mortal

    async def get(self, mortal_id: int) -> Mortal | None:
        try:
            return await self._get(mortal_id)
        except PostgresClientError as error:
            raise MortalRepositoryError(f"Failed to load Mortal {mortal_id}") from error

    async def reset(self, mortal_id: int) -> Mortal:
        defaults = {
            "locale": None,
            "timezone": DEFAULT_MORTAL_TIMEZONE,
            "notification_cron": DEFAULT_MORTAL_NOTIFICATION_CRON,
            "death_date": None,
            "llm_requests_remaining": DEFAULT_LLM_REQUESTS_REMAINING,
        }
        statement = (
            insert(mortals)
            .values(id=mortal_id, **defaults)
            .on_conflict_do_update(
                index_elements=[mortal_id_column],
                set_=defaults,
            )
        )
        try:
            await self._postgres.execute(statement)
            mortal = await self._get(mortal_id)
        except PostgresClientError as error:
            raise MortalRepositoryError(f"Failed to reset Mortal {mortal_id}") from error
        if mortal is None:
            raise MortalRepositoryError(f"Reset Mortal {mortal_id} was not found")
        return mortal

    async def set_death_date(self, mortal_id: int, death_date: date) -> Mortal:
        statement = (
            insert(mortals)
            .values(
                id=mortal_id,
                locale=None,
                timezone=DEFAULT_MORTAL_TIMEZONE,
                notification_cron=DEFAULT_MORTAL_NOTIFICATION_CRON,
                death_date=death_date,
                llm_requests_remaining=DEFAULT_LLM_REQUESTS_REMAINING,
            )
            .on_conflict_do_update(
                index_elements=[mortal_id_column],
                set_={"death_date": death_date},
            )
        )
        try:
            await self._postgres.execute(statement)
            mortal = await self._get(mortal_id)
        except PostgresClientError as error:
            raise MortalRepositoryError(
                f"Failed to set death date for Mortal {mortal_id}"
            ) from error
        if mortal is None:
            raise MortalRepositoryError(f"Updated Mortal {mortal_id} was not found")
        return mortal

    async def set_notification_cron(
        self,
        mortal_id: int,
        cron: str | None,
    ) -> Mortal:
        statement = (
            update(mortals).where(mortal_id_column == mortal_id).values(notification_cron=cron)
        )
        try:
            await self._postgres.execute(statement)
            mortal = await self._get(mortal_id)
        except PostgresClientError as error:
            raise MortalRepositoryError(
                f"Failed to set notification frequency for Mortal {mortal_id}"
            ) from error
        if mortal is None:
            raise MortalRepositoryError(f"Mortal {mortal_id} was not found")
        return mortal

    async def set_locale(self, mortal_id: int, locale: str) -> Mortal:
        statement = update(mortals).where(mortal_id_column == mortal_id).values(locale=locale)
        try:
            await self._postgres.execute(statement)
            mortal = await self._get(mortal_id)
        except PostgresClientError as error:
            raise MortalRepositoryError(f"Failed to set locale for Mortal {mortal_id}") from error
        if mortal is None:
            raise MortalRepositoryError(f"Mortal {mortal_id} was not found")
        return mortal

    async def consume_llm_request(self, mortal_id: int, request_id: str) -> Mortal:
        remaining = mortal_llm_requests_remaining_column
        consumed = (
            insert(llm_request_consumptions)
            .from_select(
                ["request_id", "mortal_id"],
                select(literal(request_id), mortal_id_column).where(
                    mortal_id_column == mortal_id,
                    remaining > 0,
                ),
            )
            .on_conflict_do_nothing(index_elements=[llm_request_id_column])
            .returning(llm_request_mortal_id_column)
            .cte("consumed")
        )
        statement = (
            update(mortals)
            .where(
                mortal_id_column == mortal_id,
                exists(select(consumed.c.mortal_id)),
            )
            .values(llm_requests_remaining=remaining - 1)
            .returning(mortals)
        )
        try:
            row = await self._postgres.execute_returning_one(statement)
            if row is not None:
                return Mortal.model_validate(dict(row))
            mortal = await self._get(mortal_id)
            prior = await self._postgres.fetch_one(
                select(llm_request_id_column).where(
                    llm_request_id_column == request_id,
                    llm_request_mortal_id_column == mortal_id,
                )
            )
        except PostgresClientError as error:
            raise MortalRepositoryError(
                f"Failed to consume LLM request for Mortal {mortal_id}"
            ) from error
        if mortal is None:
            raise MortalRepositoryError(f"Mortal {mortal_id} was not found")
        if prior is not None:
            return mortal
        raise MortalQuotaExhaustedError(f"Mortal {mortal_id} exhausted the LLM request limit")

    async def delete(self, mortal_id: int) -> None:
        try:
            await self._postgres.execute(delete(mortals).where(mortal_id_column == mortal_id))
        except PostgresClientError as error:
            raise MortalRepositoryError(f"Failed to delete Mortal {mortal_id}") from error

    async def _get(self, mortal_id: int) -> Mortal | None:
        row = await self._postgres.fetch_one(select(mortals).where(mortal_id_column == mortal_id))
        return Mortal.model_validate(dict(row)) if row is not None else None
