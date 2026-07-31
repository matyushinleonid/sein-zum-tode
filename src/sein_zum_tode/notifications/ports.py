from typing import Protocol

from sein_zum_tode.mortals.models import Mortal


class MortalSchedule(Protocol):
    async def ensure(self, mortal: Mortal) -> None: ...

    async def delete(self, mortal_id: int) -> None: ...
