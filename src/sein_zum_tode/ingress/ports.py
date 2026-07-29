import asyncio
from collections.abc import Sequence
from typing import Protocol

from aiogram.types import Update

from sein_zum_tode.ingress.models import StoredUpdate


class UpdateSource(Protocol):
    async def prepare(self) -> None: ...

    async def receive(self, offset: int | None) -> Sequence[Update]: ...


class KeyValueClient(Protocol):
    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
    ) -> bool | str | bytes | None: ...


class UpdateStore(Protocol):
    async def store(self, update: Update) -> StoredUpdate: ...


class UpdateUserResolver(Protocol):
    def resolve(self, update: Update) -> int | None: ...


class UpdateHandoff(Protocol):
    async def handoff(self, update: StoredUpdate) -> None: ...


class UserWorkflowStarter(Protocol):
    async def signal_with_start(
        self,
        *,
        user_id: int,
        update_key: str,
    ) -> None: ...


class RetryWaiter(Protocol):
    async def wait(self, failure_count: int, stop_event: asyncio.Event) -> None: ...
