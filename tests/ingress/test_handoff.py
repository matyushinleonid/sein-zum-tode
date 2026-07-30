import pytest
from temporalio.exceptions import TemporalError

from sein_zum_tode.ingress.errors import UpdateHandoffError
from sein_zum_tode.ingress.handoff import LoggingUpdateHandoff, TemporalUpdateHandoff
from sein_zum_tode.ingress.models import StoredUpdate
from tests.support import SilentLogger, WorkflowStarterDouble

pytestmark = pytest.mark.fast


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
