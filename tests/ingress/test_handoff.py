import pytest
from temporalio.exceptions import TemporalError

from sein_zum_tode.ingress.errors import UpdateHandoffError
from sein_zum_tode.ingress.handoff import (
    LoggingUpdateHandoff,
    TemporalUpdateHandoff,
    WhitelistedUpdateHandoff,
)
from sein_zum_tode.ingress.models import StoredUpdate
from sein_zum_tode.ports.metrics import NoopApplicationMetrics
from tests.support import SilentLogger, WorkflowStarterDouble

pytestmark = pytest.mark.fast


class UpdateHandoffMemory:
    def __init__(self) -> None:
        self.updates: list[StoredUpdate] = []

    async def handoff(self, update: StoredUpdate) -> None:
        self.updates.append(update)


class UpdateMetricsMemory(NoopApplicationMetrics):
    def __init__(self) -> None:
        self.events: list[tuple[str, str, int]] = []

    def updates(self, *, stage: str, outcome: str, count: int = 1) -> None:
        self.events.append((stage, outcome, count))


@pytest.mark.parametrize(
    ("allowed_user_ids", "user_id"),
    [
        (frozenset(), 102_101),
        (frozenset({102_103}), 102_103),
        (frozenset({102_107}), None),
    ],
)
async def test_forwards_an_update_permitted_by_the_access_policy(
    allowed_user_ids: frozenset[int],
    user_id: int | None,
) -> None:
    delegate = UpdateHandoffMemory()
    handoff = WhitelistedUpdateHandoff(
        delegate=delegate,
        allowed_user_ids=allowed_user_ids,
        logger=SilentLogger(),
    )
    update = StoredUpdate(
        update_id=1021,
        key="telegram:meteorites:1021",
        ttl_seconds=1023,
        user_id=user_id,
    )

    await handoff.handoff(update)

    assert delegate.updates == [update], "access policy blocked a permitted Telegram update"


async def test_silently_rejects_an_update_from_outside_the_whitelist() -> None:
    delegate = UpdateHandoffMemory()
    metrics = UpdateMetricsMemory()
    handoff = WhitelistedUpdateHandoff(
        delegate=delegate,
        allowed_user_ids=frozenset({103_301}),
        logger=SilentLogger(),
        metrics=metrics,
    )
    update = StoredUpdate(
        update_id=1033,
        key="telegram:meteorites:1033",
        ttl_seconds=1039,
        user_id=103_303,
    )

    await handoff.handoff(update)

    assert (delegate.updates, metrics.events) == (
        [],
        [("handoff", "not_allowed", 1)],
    ), "access policy forwarded a forbidden Telegram update"


async def test_forwards_a_routable_reference_to_temporal() -> None:
    starter = WorkflowStarterDouble(None)
    handoff = TemporalUpdateHandoff(starter, SilentLogger())
    update = StoredUpdate(
        update_id=1031,
        key="telegram:meteorites:1031",
        ttl_seconds=1033,
        user_id=103_339,
    )

    await handoff.handoff(update)

    assert starter.events == [(103_339, "telegram:meteorites:1031")], (
        "handoff changed the user route or Redis reference"
    )


async def test_accepts_an_unroutable_reference_without_starting_a_workflow() -> None:
    starter = WorkflowStarterDouble(None)
    handoff = TemporalUpdateHandoff(starter, SilentLogger())
    update = StoredUpdate(
        update_id=1039,
        key="telegram:meteorites:1039",
        ttl_seconds=1049,
        user_id=None,
    )

    await handoff.handoff(update)

    assert starter.events == [], "handoff started a workflow without a Telegram user"


async def test_translates_temporal_failure_for_the_poller_retry_loop() -> None:
    starter = WorkflowStarterDouble(TemporalError("temporal eclipse 1051"))
    handoff = TemporalUpdateHandoff(starter, SilentLogger())
    update = StoredUpdate(
        update_id=1061,
        key="telegram:meteorites:1061",
        ttl_seconds=1063,
        user_id=106_109,
    )

    with pytest.raises(UpdateHandoffError):
        await handoff.handoff(update)


async def test_completes_the_logging_only_handoff_contract() -> None:
    handoff = LoggingUpdateHandoff(SilentLogger())
    update = StoredUpdate(
        update_id=1069,
        key="telegram:meteorites:1069",
        ttl_seconds=1087,
        user_id=106_123,
    )

    await handoff.handoff(update)
