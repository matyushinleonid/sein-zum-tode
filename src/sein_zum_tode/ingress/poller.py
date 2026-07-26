import asyncio
import logging
from dataclasses import dataclass

from aiogram.types import Update

from sein_zum_tode.ingress.errors import (
    UpdateHandoffError,
    UpdateSourceError,
    UpdateStoreError,
)
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.ports import RetryWaiter, UpdateHandoff, UpdateSource, UpdateStore


@dataclass(frozen=True, slots=True)
class ExponentialRetryWaiter:
    initial_delay_seconds: float
    max_delay_seconds: float

    def delay(self, failure_count: int) -> float:
        exponent = min(max(failure_count - 1, 0), 30)
        return min(
            self.initial_delay_seconds * pow(2.0, exponent),
            self.max_delay_seconds,
        )

    async def wait(self, failure_count: int, stop_event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=self.delay(failure_count),
            )
        except TimeoutError:
            return


class TelegramPoller:
    def __init__(
        self,
        source: UpdateSource,
        store: UpdateStore,
        handoff: UpdateHandoff,
        retry_waiter: RetryWaiter,
        logger: logging.Logger | None = None,
    ) -> None:
        self._source = source
        self._store = store
        self._handoff = handoff
        self._retry_waiter = retry_waiter
        self._logger = logger or logging.getLogger(__name__)

    async def run(self, stop_event: asyncio.Event) -> None:
        if not await self._prepare(stop_event):
            return

        offset: int | None = None
        receive_failures = 0
        while not stop_event.is_set():
            try:
                updates = await self._source.receive(offset)
                receive_failures = 0
            except UpdateSourceError:
                receive_failures += 1
                self._logger.exception(
                    "Failed to receive Telegram updates; retrying",
                    extra={"failure_count": receive_failures},
                )
                await self._wait(receive_failures, stop_event)
                continue

            for update in updates:
                stored = await self._ingest(update, stop_event)
                if stored is None:
                    return
                offset = stored.next_offset()

    async def _prepare(self, stop_event: asyncio.Event) -> bool:
        failure_count = 0
        while not stop_event.is_set():
            try:
                await self._source.prepare()
            except UpdateSourceError:
                failure_count += 1
                self._logger.exception(
                    "Failed to prepare Telegram polling; retrying",
                    extra={"failure_count": failure_count},
                )
                await self._wait(failure_count, stop_event)
            else:
                return True
        return False

    async def _ingest(
        self,
        update: Update,
        stop_event: asyncio.Event,
    ) -> StoredUpdate | None:
        failure_count = 0
        while not stop_event.is_set():
            try:
                stored = await self._store.store(update)
                await self._handoff.handoff(stored)
            except UpdateStoreError, UpdateHandoffError:
                failure_count += 1
                self._logger.exception(
                    "Failed to store or hand off Telegram update; retrying",
                    extra={
                        "failure_count": failure_count,
                        "update_id": update.update_id,
                    },
                )
                await self._wait(failure_count, stop_event)
            else:
                return stored
        return None

    async def _wait(
        self,
        failure_count: int,
        stop_event: asyncio.Event,
    ) -> None:
        await self._retry_waiter.wait(failure_count, stop_event)
