import asyncio
from collections.abc import Awaitable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from aiogram.types import Update
from temporalio.common import WorkflowIDConflictPolicy

from sein_zum_tode.bot.models import TelegramUpdateSignal, UserWorkflowInput
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


class UpdateAdmission(Protocol):
    def admits(self, update: Update) -> bool: ...


class UpdateHandoff(Protocol):
    async def handoff(self, update: StoredUpdate) -> None: ...


class UserWorkflowStarter(Protocol):
    def signal_with_start(
        self,
        *,
        user_id: int,
        update_key: str,
    ) -> Awaitable[None]: ...


class TemporalWorkflowClient(Protocol):
    def start_workflow(
        self,
        workflow: str,
        arg: UserWorkflowInput,
        *,
        id: str,
        task_queue: str,
        id_conflict_policy: WorkflowIDConflictPolicy,
        start_signal: str | None,
        start_signal_args: Sequence[TelegramUpdateSignal],
    ) -> Awaitable[object]: ...


class RetryWaiter(Protocol):
    async def wait(self, failure_count: int, stop_event: asyncio.Event) -> None: ...


class PollingHealth(Protocol):
    def polling_started(self) -> None: ...

    def polling_succeeded(self) -> None: ...


class PollingLease(Protocol):
    def release(self) -> Awaitable[None]: ...


class PollingLeaseStore(Protocol):
    def acquire(
        self,
        *,
        holder_identity: str,
        duration_seconds: int,
    ) -> Awaitable[PollingLease | None]: ...


class PollingTurnWaiter(Protocol):
    def wait(
        self,
        delay_seconds: float,
        stop_event: asyncio.Event,
    ) -> Awaitable[None]: ...


class PollingTurnCoordinator(Protocol):
    def turn(
        self,
        stop_event: asyncio.Event,
    ) -> AbstractAsyncContextManager[bool]: ...
