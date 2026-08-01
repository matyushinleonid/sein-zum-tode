from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_MORTAL_TIMEZONE = "Europe/Moscow"
DEFAULT_MORTAL_NOTIFICATION_CRON = "0 9 * * *"
DEFAULT_LLM_REQUESTS_REMAINING = 50


class Mortal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    timezone: str = Field(default=DEFAULT_MORTAL_TIMEZONE, min_length=1, max_length=64)
    notification_cron: str | None = Field(
        default=DEFAULT_MORTAL_NOTIFICATION_CRON,
        min_length=1,
        max_length=128,
    )
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

    def can_request_prediction(self) -> bool:
        return self.llm_requests_remaining > 0
