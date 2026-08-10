import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from sein_zum_tode.ingress.errors import PollingLeaseError
from sein_zum_tode.ingress.ports import PollingLease, PollingLeaseStore, PollingTurnWaiter
from sein_zum_tode.observability import LogContext


@dataclass(frozen=True, slots=True)
class AsyncioPollingTurnWaiter:
    async def wait(
        self,
        delay_seconds: float,
        stop_event: asyncio.Event,
    ) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay_seconds)
        except TimeoutError:
            return


class UncoordinatedPollingTurns:
    def turn(self, stop_event: asyncio.Event) -> AbstractAsyncContextManager[bool]:
        return self._turn(stop_event)

    @asynccontextmanager
    async def _turn(self, stop_event: asyncio.Event) -> AsyncIterator[bool]:
        yield not stop_event.is_set()


class LeaseCoordinatedPollingTurns:
    def __init__(
        self,
        *,
        leases: PollingLeaseStore,
        holder_identity: str,
        lease_duration_seconds: int,
        retry_interval_seconds: float,
        handoff_delay_seconds: float,
        waiter: PollingTurnWaiter | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._leases = leases
        self._holder_identity = holder_identity
        self._lease_duration_seconds = lease_duration_seconds
        self._retry_interval_seconds = retry_interval_seconds
        self._handoff_delay_seconds = handoff_delay_seconds
        self._waiter = waiter or AsyncioPollingTurnWaiter()
        self._logger = logger or logging.getLogger(__name__)

    def turn(self, stop_event: asyncio.Event) -> AbstractAsyncContextManager[bool]:
        return self._turn(stop_event)

    @asynccontextmanager
    async def _turn(self, stop_event: asyncio.Event) -> AsyncIterator[bool]:
        lease = await self._acquire(stop_event)
        try:
            yield lease is not None
        finally:
            if lease is not None:
                await self._release(lease)
                await self._waiter.wait(self._handoff_delay_seconds, stop_event)

    async def _acquire(self, stop_event: asyncio.Event) -> PollingLease | None:
        while not stop_event.is_set():
            try:
                lease = await self._leases.acquire(
                    holder_identity=self._holder_identity,
                    duration_seconds=self._lease_duration_seconds,
                )
            except PollingLeaseError:
                self._logger.exception(
                    "Failed to coordinate Telegram polling; retrying",
                    extra=LogContext(component="ingress").event(
                        "telegram_poll_coordination_failed",
                        stage="acquire",
                    ),
                )
            else:
                if lease is not None:
                    return lease
            await self._waiter.wait(self._retry_interval_seconds, stop_event)
        return None

    async def _release(self, lease: PollingLease) -> None:
        try:
            await lease.release()
        except PollingLeaseError:
            self._logger.exception(
                "Failed to release Telegram polling lease",
                extra=LogContext(component="ingress").event(
                    "telegram_poll_coordination_failed",
                    stage="release",
                ),
            )
