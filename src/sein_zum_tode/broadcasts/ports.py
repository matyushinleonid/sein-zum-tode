from typing import Protocol

from sein_zum_tode.broadcasts.models import ScreamRequest


class TelegramMessageCopier(Protocol):
    async def copy(self, request: ScreamRequest, recipient_id: int) -> None: ...


class MortalAudience(Protocol):
    async def list_ids(
        self,
        *,
        locale: str,
        after_mortal_id: int | None,
        limit: int,
    ) -> tuple[int, ...]: ...
