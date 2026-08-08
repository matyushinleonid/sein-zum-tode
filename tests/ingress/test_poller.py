import asyncio

import pytest

from sein_zum_tode.ingress.errors import (
    UpdateHandoffError,
    UpdateSourceError,
    UpdateStoreError,
)
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ingress.poller import ExponentialRetryWaiter, TelegramPoller
from tests.support import (
    AdmissionDouble,
    HandoffDouble,
    RetryWaiterDouble,
    SilentLogger,
    SourceDouble,
    StoreDouble,
    TelegramUpdates,
)

pytestmark = pytest.mark.fast


def poller(
    *,
    source: SourceDouble,
    store: StoreDouble,
    handoff: HandoffDouble,
    waiter: RetryWaiterDouble,
    admission: AdmissionDouble | None = None,
) -> TelegramPoller:
    return TelegramPoller(
        source=source,
        store=store,
        admission=admission or AdmissionDouble(),
        handoff=handoff,
        retry_waiter=waiter,
        logger=SilentLogger(),
    )


@pytest.mark.parametrize(
    ("failure_count", "expected"),
    [(0, 0.37), (1, 0.37), (2, 0.74), (4, 2.96), (10_000, 3.1)],
)
def test_caps_exponential_retry_delay(failure_count: int, expected: float) -> None:
    actual = ExponentialRetryWaiter(0.37, 3.1).delay(failure_count)

    assert actual == expected, "retry delay escaped its exponential schedule or maximum cap"


async def test_finishes_retry_wait_after_its_timeout() -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()

    await ExponentialRetryWaiter(0.001, 0.001).wait(17, asyncio.Event())

    assert loop.time() - started < 0.1, "retry waiter did not return after its timeout"


async def test_interrupts_retry_wait_on_shutdown() -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    loop = asyncio.get_running_loop()
    started = loop.time()

    await ExponentialRetryWaiter(97.0, 101.0).wait(19, stop_event)

    assert loop.time() - started < 0.1, "retry waiter ignored an application shutdown"


async def test_processes_updates_in_order_before_advancing_offset() -> None:
    stop = asyncio.Event()
    first = TelegramUpdates.message(
        update_id=1117,
        user_id=111_731,
        chat_id=111_733,
        text="Quick zephyrs blow",
        chat_type="private",
    )
    second = TelegramUpdates.message(
        update_id=1123,
        user_id=112_397,
        chat_id=112_403,
        text="Vexing daft zebras",
        chat_type="private",
    )
    stored = [
        StoredUpdate(
            update_id=1117,
            key="telegram:zephyrs:1117",
            ttl_seconds=1129,
            user_id=111_731,
        ),
        StoredUpdate(
            update_id=1123,
            key="telegram:zebras:1123",
            ttl_seconds=1151,
            user_id=112_397,
        ),
    ]
    source = SourceDouble(
        prepare_outcomes=[None],
        receive_outcomes=[[first, second], []],
        stop_event=stop,
    )
    store = StoreDouble(stored.copy())
    handoff = HandoffDouble([None, None])
    waiter = RetryWaiterDouble(False)

    await poller(source=source, store=store, handoff=handoff, waiter=waiter).run(stop)

    assert (source.events, store.events, handoff.events, waiter.events) == (
        [("prepare", 1), ("receive", None), ("receive", 1124)],
        [1117, 1123],
        stored,
        [],
    ), "poller acknowledged an update before ordered storage and handoff"


async def test_never_stores_an_update_refused_by_admission() -> None:
    stop = asyncio.Event()
    refused = TelegramUpdates.message(
        update_id=1289,
        user_id=128_981,
        chat_id=128_983,
        text="Blowzy night-frumps",
        chat_type="private",
    )
    admitted = TelegramUpdates.message(
        update_id=1291,
        user_id=129_113,
        chat_id=129_127,
        text="Jaded zombies acted",
        chat_type="private",
    )
    stored = StoredUpdate(
        update_id=1291,
        key="telegram:zombies:1291",
        ttl_seconds=1297,
        user_id=129_113,
    )
    source = SourceDouble(
        prepare_outcomes=[None],
        receive_outcomes=[[refused, admitted], []],
        stop_event=stop,
    )
    store = StoreDouble([stored])
    handoff = HandoffDouble([None])
    admission = AdmissionDouble(frozenset({1289}))

    await poller(
        source=source,
        store=store,
        handoff=handoff,
        waiter=RetryWaiterDouble(False),
        admission=admission,
    ).run(stop)

    assert (admission.events, store.events, handoff.events, source.events) == (
        [1289, 1291],
        [1291],
        [stored],
        [("prepare", 1), ("receive", None), ("receive", 1292)],
    ), "refused update reached Redis or blocked the polling offset"


async def test_retries_source_preparation_before_polling() -> None:
    stop = asyncio.Event()
    source = SourceDouble(
        prepare_outcomes=[UpdateSourceError("solar flare 1153"), None],
        receive_outcomes=[[]],
        stop_event=stop,
    )
    store = StoreDouble([])
    handoff = HandoffDouble([])
    waiter = RetryWaiterDouble(False)

    await poller(source=source, store=store, handoff=handoff, waiter=waiter).run(stop)

    assert (source.events, waiter.events) == (
        [("prepare", 2), ("prepare", 1), ("receive", None)],
        [1],
    ), "poller did not retry source preparation with the first backoff"


async def test_stops_during_source_preparation_backoff() -> None:
    stop = asyncio.Event()
    source = SourceDouble(
        prepare_outcomes=[UpdateSourceError("coronal mass 1163")],
        receive_outcomes=[],
        stop_event=stop,
    )
    waiter = RetryWaiterDouble(True)

    await poller(
        source=source,
        store=StoreDouble([]),
        handoff=HandoffDouble([]),
        waiter=waiter,
    ).run(stop)

    assert source.events == [("prepare", 1)], (
        "poller contacted Telegram after shutdown interrupted preparation"
    )


async def test_propagates_an_unexpected_source_failure() -> None:
    stop = asyncio.Event()
    source = SourceDouble(
        prepare_outcomes=[RuntimeError("broken invariant 1171")],
        receive_outcomes=[],
        stop_event=stop,
    )
    subject = poller(
        source=source,
        store=StoreDouble([]),
        handoff=HandoffDouble([]),
        waiter=RetryWaiterDouble(False),
    )

    with pytest.raises(RuntimeError):
        await subject.run(stop)


async def test_recovers_from_a_receive_failure_without_losing_offset() -> None:
    stop = asyncio.Event()
    update = TelegramUpdates.message(
        update_id=1181,
        user_id=118_187,
        chat_id=118_189,
        text="Crazy Fredrick",
        chat_type="private",
    )
    stored = StoredUpdate(
        update_id=1181,
        key="telegram:fredrick:1181",
        ttl_seconds=1193,
        user_id=118_187,
    )
    source = SourceDouble(
        prepare_outcomes=[None],
        receive_outcomes=[UpdateSourceError("ionosphere 1201"), [update], []],
        stop_event=stop,
    )
    handoff = HandoffDouble([None])
    waiter = RetryWaiterDouble(False)

    await poller(
        source=source,
        store=StoreDouble([stored]),
        handoff=handoff,
        waiter=waiter,
    ).run(stop)

    assert (source.events, waiter.events, handoff.events) == (
        [
            ("prepare", 1),
            ("receive", None),
            ("receive", None),
            ("receive", 1182),
        ],
        [1],
        [stored],
    ), "poller changed offset or duplicated handoff after receive recovery"


@pytest.mark.parametrize("failing_boundary", ["store", "handoff"])
async def test_restores_payload_ttl_before_every_ingest_retry(failing_boundary: str) -> None:
    stop = asyncio.Event()
    update = TelegramUpdates.message(
        update_id=1213,
        user_id=121_309,
        chat_id=121_313,
        text="Five quacking zephyrs",
        chat_type="private",
    )
    stored = StoredUpdate(
        update_id=1213,
        key="telegram:quacking:1213",
        ttl_seconds=1217,
        user_id=121_309,
    )
    store_outcomes = (
        [UpdateStoreError("redis 1223"), stored]
        if failing_boundary == "store"
        else [stored, stored]
    )
    handoff_outcomes = (
        [None] if failing_boundary == "store" else [UpdateHandoffError("temporal 1229"), None]
    )
    source = SourceDouble(
        prepare_outcomes=[None],
        receive_outcomes=[[update], []],
        stop_event=stop,
    )
    store = StoreDouble(store_outcomes)
    handoff = HandoffDouble(handoff_outcomes)
    waiter = RetryWaiterDouble(False)

    await poller(source=source, store=store, handoff=handoff, waiter=waiter).run(stop)

    assert (store.events, len(handoff.events), waiter.events) == (
        [1213, 1213],
        1 if failing_boundary == "store" else 2,
        [1],
    ), "ingest retry failed to rewrite Redis payload and refresh its TTL"


async def test_stops_during_handoff_backoff_without_advancing_offset() -> None:
    stop = asyncio.Event()
    update = TelegramUpdates.message(
        update_id=1231,
        user_id=123_137,
        chat_id=123_143,
        text="Woven silk pyjamas",
        chat_type="private",
    )
    stored = StoredUpdate(
        update_id=1231,
        key="telegram:silk:1231",
        ttl_seconds=1237,
        user_id=123_137,
    )
    source = SourceDouble(
        prepare_outcomes=[None],
        receive_outcomes=[[update], []],
        stop_event=stop,
    )
    store = StoreDouble([stored])
    handoff = HandoffDouble([UpdateHandoffError("workflow frozen 1249")])

    await poller(
        source=source,
        store=store,
        handoff=handoff,
        waiter=RetryWaiterDouble(True),
    ).run(stop)

    assert source.events == [
        ("prepare", 1),
        ("receive", None),
    ], "poller requested a newer offset after an interrupted handoff"
