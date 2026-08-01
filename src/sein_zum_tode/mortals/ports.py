from datetime import date
from typing import Protocol

from sein_zum_tode.mortals.models import Mortal


class MortalRepository(Protocol):
    async def ensure(self, mortal_id: int) -> Mortal: ...

    async def get(self, mortal_id: int) -> Mortal | None: ...

    async def set_death_date(self, mortal_id: int, death_date: date) -> Mortal: ...

    async def set_notification_cron(
        self,
        mortal_id: int,
        cron: str | None,
    ) -> Mortal: ...

    async def set_notification_settings(
        self,
        mortal_id: int,
        *,
        cron: str | None,
        timezone: str,
    ) -> Mortal: ...

    async def set_locale(self, mortal_id: int, locale: str) -> Mortal: ...

    async def consume_llm_request(self, mortal_id: int, request_id: str) -> Mortal: ...

    async def mark_unreachable(self, mortal_id: int) -> None: ...
