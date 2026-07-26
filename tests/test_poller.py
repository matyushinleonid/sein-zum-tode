import asyncio
from collections.abc import Callable
from unittest.mock import create_autospec

import pytest
from aiogram.types import Update

from sein_zum_tode.ingress.errors import (
    UpdateHandoffError,
    UpdateSourceError,
)
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.poller import ExponentialRetryWaiter, TelegramPoller
from sein_zum_tode.ingress.ports import RetryWaiter, UpdateHandoff, UpdateSource, UpdateStore


def build_poller(
    source: UpdateSource,
    store: UpdateStore,
    handoff: UpdateHandoff,
    waiter: RetryWaiter,
) -> TelegramPoller:
    return TelegramPoller(
        source=source,
        store=store,
        handoff=handoff,
        retry_waiter=waiter,
    )


def test_retry_waiter_uses_capped_exponential_delay() -> None:
    waiter = ExponentialRetryWaiter(initial_delay_seconds=0.5, max_delay_seconds=2.0)

    assert waiter.delay(0) == 0.5
    assert waiter.delay(1) == 0.5
    assert waiter.delay(2) == 1.0
    assert waiter.delay(3) == 2.0
    assert waiter.delay(100) == 2.0


async def test_retry_waiter_returns_after_timeout() -> None:
    waiter = ExponentialRetryWaiter(
        initial_delay_seconds=0.001,
        max_delay_seconds=0.001,
    )

    await waiter.wait(1, asyncio.Event())


async def test_retry_waiter_returns_when_stopped() -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    waiter = ExponentialRetryWaiter(
        initial_delay_seconds=10,
        max_delay_seconds=10,
    )

    await waiter.wait(1, stop_event)


async def test_poller_stores_and_hands_off_every_update_before_advancing_offset(
    make_update: Callable[[int, str], Update],
) -> None:
    first_update = make_update(10, "first")
    second_update = make_update(11, "second")
    first_stored = StoredUpdate(10, "updates:10", 600)
    second_stored = StoredUpdate(11, "updates:11", 600)
    source = create_autospec(UpdateSource, instance=True)
    store = create_autospec(UpdateStore, instance=True)
    handoff = create_autospec(UpdateHandoff, instance=True)
    waiter = create_autospec(RetryWaiter, instance=True)
    stop_event = asyncio.Event()
    calls = 0

    async def receive(offset: int | None):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert offset is None
            return [first_update, second_update]
        assert offset == 12
        stop_event.set()
        return []

    source.receive.side_effect = receive
    store.store.side_effect = [first_stored, second_stored]
    poller = build_poller(source, store, handoff, waiter)

    await poller.run(stop_event)

    source.prepare.assert_awaited_once_with()
    assert store.store.await_args_list[0].args == (first_update,)
    assert store.store.await_args_list[1].args == (second_update,)
    assert handoff.handoff.await_args_list[0].args == (first_stored,)
    assert handoff.handoff.await_args_list[1].args == (second_stored,)
    waiter.wait.assert_not_awaited()


async def test_poller_retries_source_preparation_until_success() -> None:
    source = create_autospec(UpdateSource, instance=True)
    store = create_autospec(UpdateStore, instance=True)
    handoff = create_autospec(UpdateHandoff, instance=True)
    waiter = create_autospec(RetryWaiter, instance=True)
    stop_event = asyncio.Event()
    source.prepare.side_effect = [UpdateSourceError("unavailable"), None]
    source.receive.side_effect = lambda offset: stop_event.set() or []
    poller = build_poller(source, store, handoff, waiter)

    await poller.run(stop_event)

    assert source.prepare.await_count == 2
    waiter.wait.assert_awaited_once_with(1, stop_event)


async def test_poller_stops_while_retrying_source_preparation() -> None:
    source = create_autospec(UpdateSource, instance=True)
    store = create_autospec(UpdateStore, instance=True)
    handoff = create_autospec(UpdateHandoff, instance=True)
    waiter = create_autospec(RetryWaiter, instance=True)
    stop_event = asyncio.Event()
    source.prepare.side_effect = UpdateSourceError("unavailable")
    waiter.wait.side_effect = lambda failure_count, event: event.set()
    poller = build_poller(source, store, handoff, waiter)

    await poller.run(stop_event)

    source.prepare.assert_awaited_once_with()
    source.receive.assert_not_awaited()


async def test_poller_does_not_retry_unexpected_source_errors() -> None:
    source = create_autospec(UpdateSource, instance=True)
    store = create_autospec(UpdateStore, instance=True)
    handoff = create_autospec(UpdateHandoff, instance=True)
    waiter = create_autospec(RetryWaiter, instance=True)
    stop_event = asyncio.Event()
    source.prepare.side_effect = RuntimeError("programming error")
    poller = build_poller(source, store, handoff, waiter)

    with pytest.raises(RuntimeError, match="programming error"):
        await poller.run(stop_event)

    waiter.wait.assert_not_awaited()


async def test_poller_retries_receiving_updates(
    make_update: Callable[[int, str], Update],
) -> None:
    update = make_update(10, "first")
    stored = StoredUpdate(10, "updates:10", 600)
    source = create_autospec(UpdateSource, instance=True)
    store = create_autospec(UpdateStore, instance=True)
    handoff = create_autospec(UpdateHandoff, instance=True)
    waiter = create_autospec(RetryWaiter, instance=True)
    stop_event = asyncio.Event()
    calls = 0

    async def receive(offset: int | None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise UpdateSourceError("network")
        if calls == 2:
            return [update]
        assert offset == 11
        stop_event.set()
        return []

    source.receive.side_effect = receive
    store.store.return_value = stored
    poller = build_poller(source, store, handoff, waiter)

    await poller.run(stop_event)

    assert source.receive.await_count == 3
    waiter.wait.assert_awaited_once_with(1, stop_event)
    handoff.handoff.assert_awaited_once_with(stored)


async def test_poller_restores_payload_ttl_when_handoff_is_retried(
    make_update: Callable[[int, str], Update],
) -> None:
    update = make_update(10, "first")
    stored = StoredUpdate(10, "updates:10", 600)
    source = create_autospec(UpdateSource, instance=True)
    store = create_autospec(UpdateStore, instance=True)
    handoff = create_autospec(UpdateHandoff, instance=True)
    waiter = create_autospec(RetryWaiter, instance=True)
    stop_event = asyncio.Event()
    receives = 0

    async def receive(offset: int | None):
        nonlocal receives
        receives += 1
        if receives == 1:
            return [update]
        assert offset == 11
        stop_event.set()
        return []

    source.receive.side_effect = receive
    store.store.return_value = stored
    handoff.handoff.side_effect = [UpdateHandoffError("handoff"), None]
    poller = build_poller(source, store, handoff, waiter)

    await poller.run(stop_event)

    assert store.store.await_count == 2
    assert handoff.handoff.await_count == 2
    waiter.wait.assert_awaited_once_with(1, stop_event)


async def test_poller_stops_while_retrying_handoff(
    make_update: Callable[[int, str], Update],
) -> None:
    update = make_update(10, "first")
    stored = StoredUpdate(10, "updates:10", 600)
    source = create_autospec(UpdateSource, instance=True)
    store = create_autospec(UpdateStore, instance=True)
    handoff = create_autospec(UpdateHandoff, instance=True)
    waiter = create_autospec(RetryWaiter, instance=True)
    stop_event = asyncio.Event()
    source.receive.return_value = [update]
    store.store.return_value = stored
    handoff.handoff.side_effect = UpdateHandoffError("handoff")
    waiter.wait.side_effect = lambda failure_count, event: event.set()
    poller = build_poller(source, store, handoff, waiter)

    await poller.run(stop_event)

    store.store.assert_awaited_once_with(update)
    handoff.handoff.assert_awaited_once_with(stored)
    source.receive.assert_awaited_once_with(None)
