from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_LLM_REQUESTS_REMAINING = 15


class Mortal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    timezone: str = Field(min_length=1, max_length=64)
    notification_cron: str | None = Field(min_length=1, max_length=128)
    death_date: date | None = None
    telegram_unreachable_at: datetime | None = None
    llm_requests_remaining: int = Field(
        default=DEFAULT_LLM_REQUESTS_REMAINING,
        ge=0,
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA timezone") from error
        return value

    def days_left(self, now: datetime) -> int | None:
        if self.death_date is None:
            return None
        return max(0, (self.death_date - self.local_date(now)).days)

    def local_date(self, now: datetime) -> date:
        if now.utcoffset() is None:
            raise ValueError("now must include timezone information")
        return now.astimezone(ZoneInfo(self.timezone)).date()

    def seconds_until_next_local_date(self, now: datetime) -> int:
        if now.utcoffset() is None:
            raise ValueError("now must include timezone information")
        timezone = ZoneInfo(self.timezone)
        local_now = now.astimezone(timezone)
        next_midnight = datetime.combine(
            local_now.date() + timedelta(days=1),
            time.min,
            tzinfo=timezone,
        )
        remaining = next_midnight.astimezone(UTC) - now.astimezone(UTC)
        return max(1, ceil(remaining.total_seconds()))

    def can_request_llm(self) -> bool:
        return self.llm_requests_remaining > 0


class MortalRegistrationDefaults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timezone: str = Field(min_length=1, max_length=64)
    notification_cron: str | None = Field(min_length=1, max_length=128)
    llm_requests_remaining: int = Field(default=DEFAULT_LLM_REQUESTS_REMAINING, ge=0)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA timezone") from error
        return value

    def mortal(self, mortal_id: int, *, death_date: date | None = None) -> Mortal:
        return Mortal(
            id=mortal_id,
            locale=None,
            timezone=self.timezone,
            notification_cron=self.notification_cron,
            death_date=death_date,
            telegram_unreachable_at=None,
            llm_requests_remaining=self.llm_requests_remaining,
        )
