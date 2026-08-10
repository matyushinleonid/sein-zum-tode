import asyncio
from collections.abc import Sequence
from typing import cast

import pytest

from sein_zum_tode.ingress.coordination import (
    AsyncioPollingTurnWaiter,
    LeaseCoordinatedPollingTurns,
    UncoordinatedPollingTurns,
)
from sein_zum_tode.ingress.errors import PollingLeaseError
from sein_zum_tode.ingress.ports import PollingLease
from tests.support import SilentLogger, result_or_raise

pytestmark = pytest.mark.fast


class PollingLeaseMemory:
    def __init__(self, outcome: object = None) -> None:
        self.outcome = outcome
        self.releases = 0

    async def release(self) -> None:
        self.releases += 1
        result_or_raise(self.outcome)


class PollingLeaseStoreMemory:
    def __init__(self, outcomes: Sequence[object]) -> None:
        self.outcomes = list(outcomes)
        self.events: list[tuple[str, int]] = []

    async def acquire(
        self,
        *,
        holder_identity: str,
        duration_seconds: int,
    ) -> PollingLease | None:
        self.events.append((holder_identity, duration_seconds))
        return cast(PollingLease | None, result_or_raise(self.outcomes.pop(0)))


class PollingTurnWaiterMemory:
    def __init__(self, *, stop_after: int | None = None) -> None:
        self.stop_after = stop_after
        self.events: list[float] = []

    async def wait(self, delay_seconds: float, stop_event: asyncio.Event) -> None:
        self.events.append(delay_seconds)
        if self.stop_after == len(self.events):
            stop_event.set()


async def test_hands_a_polling_turn_to_a_waiting_new_pod() -> None:
    lease = PollingLeaseMemory()
    leases = PollingLeaseStoreMemory(
        outcomes=[None, PollingLeaseError("apiserver unavailable 2011"), lease]
    )
    waiter = PollingTurnWaiterMemory()
    subject = LeaseCoordinatedPollingTurns(
        leases=leases,
        holder_identity="ingress-new-2017",
        lease_duration_seconds=61,
        retry_interval_seconds=0.23,
        handoff_delay_seconds=0.47,
        waiter=waiter,
        logger=SilentLogger(),
    )

    async with subject.turn(asyncio.Event()) as acquired:
        observed = acquired

    assert (observed, leases.events, waiter.events, lease.releases) == (
        True,
        [
            ("ingress-new-2017", 61),
            ("ingress-new-2017", 61),
            ("ingress-new-2017", 61),
        ],
        [0.23, 0.23, 0.47],
        1,
    ), "new ingress did not wait, acquire, release, and yield its real polling turn"


async def test_stops_waiting_for_a_polling_turn_during_shutdown() -> None:
    stop = asyncio.Event()
    leases = PollingLeaseStoreMemory(outcomes=[None])
    waiter = PollingTurnWaiterMemory(stop_after=1)
    subject = LeaseCoordinatedPollingTurns(
        leases=leases,
        holder_identity="ingress-stopping-2027",
        lease_duration_seconds=67,
        retry_interval_seconds=0.29,
        handoff_delay_seconds=0.53,
        waiter=waiter,
    )

    async with subject.turn(stop) as acquired:
        observed = acquired

    assert (observed, leases.events, waiter.events) == (
        False,
        [("ingress-stopping-2027", 67)],
        [0.29],
    ), "shutdown left ingress waiting for an unavailable Kubernetes Lease"


async def test_lets_an_expired_release_fall_back_to_lease_ttl() -> None:
    lease = PollingLeaseMemory(PollingLeaseError("release conflict 2039"))
    waiter = PollingTurnWaiterMemory()
    subject = LeaseCoordinatedPollingTurns(
        leases=PollingLeaseStoreMemory(outcomes=[lease]),
        holder_identity="ingress-release-2053",
        lease_duration_seconds=71,
        retry_interval_seconds=0.31,
        handoff_delay_seconds=0.59,
        waiter=waiter,
        logger=SilentLogger(),
    )

    async with subject.turn(asyncio.Event()) as acquired:
        observed = acquired

    assert (observed, lease.releases, waiter.events) == (
        True,
        1,
        [0.59],
    ), "a failed graceful release escaped the turn instead of relying on Lease expiry"


@pytest.mark.parametrize(("stopped", "expected"), [(False, True), (True, False)])
async def test_runs_uncoordinated_turns_outside_kubernetes(
    stopped: bool,
    expected: bool,
) -> None:
    stop = asyncio.Event()
    if stopped:
        stop.set()

    async with UncoordinatedPollingTurns().turn(stop) as acquired:
        observed = acquired

    assert observed is expected, "local polling coordination did not follow process lifecycle"


async def test_finishes_coordination_wait_after_its_timeout() -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()

    await AsyncioPollingTurnWaiter().wait(0.001, asyncio.Event())

    assert loop.time() - started < 0.1, "coordination waiter did not return after its timeout"


async def test_interrupts_coordination_wait_on_shutdown() -> None:
    stop = asyncio.Event()
    stop.set()
    loop = asyncio.get_running_loop()
    started = loop.time()

    await AsyncioPollingTurnWaiter().wait(97.0, stop)

    assert loop.time() - started < 0.1, "coordination waiter ignored application shutdown"
