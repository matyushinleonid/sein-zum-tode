import pytest

from sein_zum_tode.ingress.admission import WhitelistedUpdateAdmission
from sein_zum_tode.ingress.routing import AiogramUpdateUserResolver
from sein_zum_tode.ports.metrics import NoopApplicationMetrics
from tests.support import SilentLogger, TelegramUpdates

pytestmark = pytest.mark.fast


class UpdateMetricsMemory(NoopApplicationMetrics):
    def __init__(self) -> None:
        self.events: list[tuple[str, str, int]] = []

    def updates(self, *, stage: str, outcome: str, count: int = 1) -> None:
        self.events.append((stage, outcome, count))


def admission(
    allowed_user_ids: frozenset[int],
    metrics: NoopApplicationMetrics | None = None,
) -> WhitelistedUpdateAdmission:
    return WhitelistedUpdateAdmission(
        user_resolver=AiogramUpdateUserResolver(),
        allowed_user_ids=allowed_user_ids,
        logger=SilentLogger(),
        metrics=metrics or NoopApplicationMetrics(),
    )


@pytest.mark.parametrize(
    ("allowed_user_ids", "user_id"),
    [
        (frozenset(), 102_101),
        (frozenset({102_103}), 102_103),
        (frozenset({102_107, 102_109}), 102_109),
    ],
)
def test_admits_an_update_permitted_by_the_access_policy(
    allowed_user_ids: frozenset[int],
    user_id: int,
) -> None:
    update = TelegramUpdates.message(
        update_id=1021,
        user_id=user_id,
        chat_id=102_121,
        text="Sphinx of black quartz",
        chat_type="private",
    )

    actual = admission(allowed_user_ids).admits(update)

    assert actual is True, "access policy blocked a permitted Telegram update"


def test_rejects_an_update_without_a_resolvable_user_in_whitelist_mode() -> None:
    metrics = UpdateMetricsMemory()
    update = TelegramUpdates.anonymous_poll(update_id=1031)

    actual = admission(frozenset({103_151}), metrics).admits(update)

    assert (actual, metrics.events) == (False, [("admission", "not_allowed", 1)]), (
        "whitelist admitted an update that could not be attributed to an allowed user"
    )


def test_rejects_an_update_from_outside_the_whitelist() -> None:
    metrics = UpdateMetricsMemory()
    update = TelegramUpdates.message(
        update_id=1033,
        user_id=103_303,
        chat_id=103_307,
        text="Jackdaws love my big sphinx",
        chat_type="private",
    )

    actual = admission(frozenset({103_301}), metrics).admits(update)

    assert (actual, metrics.events) == (False, [("admission", "not_allowed", 1)]), (
        "access policy admitted a forbidden Telegram update or lost its metric"
    )
