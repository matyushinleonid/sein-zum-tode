from datetime import date, datetime
from typing import Protocol

from sein_zum_tode.bot.content import NotificationTier
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.models import RenderedNotification


class MortalSchedule(Protocol):
    async def ensure(self, mortal: Mortal) -> None: ...

    async def delete(self, mortal_id: int) -> None: ...

    async def next_action_time(self, mortal_id: int) -> datetime | None: ...


class NotificationPresenter(Protocol):
    def render(
        self,
        *,
        locale: str | None,
        days_left: int,
        seed: str,
        today: date | None = None,
        death_date: date | None = None,
        sample: NotificationTier | None = None,
    ) -> RenderedNotification: ...


class NumberSpeller(Protocol):
    def spell(self, value: int, locale: str) -> str: ...
