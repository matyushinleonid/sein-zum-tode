from typing import Protocol

from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.models import RenderedNotification


class MortalSchedule(Protocol):
    async def ensure(self, mortal: Mortal) -> None: ...

    async def delete(self, mortal_id: int) -> None: ...


class NotificationPresenter(Protocol):
    def render(
        self,
        *,
        locale: str | None,
        days_left: int,
        seed: str,
    ) -> RenderedNotification: ...


class NumberSpeller(Protocol):
    def spell(self, value: int, locale: str) -> str: ...
