import asyncio
from collections.abc import Awaitable, Sequence
from typing import Protocol

from aiogram.types import Update
from temporalio.common import WorkflowIDConflictPolicy

from sein_zum_tode.ingress.models import StoredUpdate


class UpdateSource(Protocol):
    async def prepare(self) -> None: ...

    async def receive(self, offset: int | None) -> Sequence[Update]: ...


class TelegramPollingClient(Protocol):
    async def delete_webhook(
        self,
        drop_pending_updates: bool | None = None,
        request_timeout: int | None = None,
    ) -> object: ...

    def get_updates(
        self,
        offset: int | None = None,
        limit: int | None = None,
        timeout: int | None = None,
        allowed_updates: list[str] | None = None,
        request_timeout: int | None = None,
    ) -> Awaitable[Sequence[Update]]: ...


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


class TemporalWorkflowClient(Protocol):
    async def start_workflow(
        self,
        workflow: str,
        arg: object,
        *,
        id: str,
        task_queue: str,
        id_conflict_policy: WorkflowIDConflictPolicy,
        start_signal: str | None,
        start_signal_args: Sequence[object],
    ) -> object: ...


class RetryWaiter(Protocol):
    async def wait(self, failure_count: int, stop_event: asyncio.Event) -> None: ...
