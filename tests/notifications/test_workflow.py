from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from temporalio import workflow as temporal_workflow
from temporalio.converter import DataConverter
from temporalio.exceptions import ActivityError, ApplicationError

from sein_zum_tode.bot.models import (
    CLEANUP_PAYLOADS_ACTIVITY_NAME,
    DELIVER_RESPONSE_ACTIVITY_NAME,
)
from sein_zum_tode.mortals.activities import (
    DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
    MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME,
)
from sein_zum_tode.notifications.models import (
    PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
    MortalNotificationDeliveryPlan,
    MortalNotificationWorkflowInput,
    PreparedMortalNotification,
)
from sein_zum_tode.notifications.workflow import MortalNotificationWorkflow

pytestmark = pytest.mark.fast


def activity_error(cause: BaseException | None = None) -> ActivityError:
    error = ActivityError(
        "notification activity failed",
        scheduled_event_id=3701,
        started_event_id=3703,
        identity="worker-3707",
        activity_type="notification",
        activity_id="activity-3713",
        retry_state=None,
    )
    error.__cause__ = cause
    return error


async def test_decodes_legacy_workflow_input_without_a_delivery_deadline() -> None:
    payloads = await DataConverter.default.encode(
        [
            {
                "mortal_id": 370_001,
                "activity_retry_timeout_seconds": 300,
            }
        ]
    )

    actual = await DataConverter.default.decode(
        payloads,
        [MortalNotificationWorkflowInput],
    )

    assert actual == [
        MortalNotificationWorkflowInput(
            mortal_id=370_001,
            activity_retry_timeout_seconds=300,
        )
    ], "new workflow input could not decode a pre-deployment Schedule payload"


async def test_round_trips_a_delivery_plan_through_the_temporal_converter() -> None:
    expected = MortalNotificationDeliveryPlan.ending_at(
        datetime(2100, 1, 2, 8, 0, tzinfo=UTC),
    )
    payloads = await DataConverter.default.encode([expected])

    actual = await DataConverter.default.decode(
        payloads,
        [MortalNotificationDeliveryPlan],
    )

    assert actual == [expected], "delivery plan could not cross the Temporal boundary"


async def test_runs_the_historical_terminal_notification_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def execute_activity(name: str, *_: object, **__: object) -> object:
        events.append(name)
        if name == PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME:
            return PreparedMortalNotification(response_key="response:3709", days_left=0)
        return None

    monkeypatch.setattr(temporal_workflow, "patched", lambda _: False)
    monkeypatch.setattr(
        temporal_workflow,
        "info",
        lambda: SimpleNamespace(run_id="legacy-run-3709"),
    )
    monkeypatch.setattr(temporal_workflow, "execute_activity", execute_activity)

    await MortalNotificationWorkflow().run(
        MortalNotificationWorkflowInput(
            mortal_id=370_009,
            activity_retry_timeout_seconds=300,
        )
    )

    assert events == [
        PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
        DELIVER_RESPONSE_ACTIVITY_NAME,
        CLEANUP_PAYLOADS_ACTIVITY_NAME,
        DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
    ], "historical notification did not preserve its terminal delivery lifecycle"


async def test_reconciles_the_historical_notification_without_a_mortal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def execute_activity(name: str, *_: object, **__: object) -> object:
        events.append(name)
        return None

    monkeypatch.setattr(
        temporal_workflow,
        "info",
        lambda: SimpleNamespace(run_id="legacy-run-3719"),
    )
    monkeypatch.setattr(temporal_workflow, "execute_activity", execute_activity)

    await MortalNotificationWorkflow()._run_legacy(
        MortalNotificationWorkflowInput(
            mortal_id=370_019,
            activity_retry_timeout_seconds=300,
        )
    )

    assert events == [
        PREPARE_MORTAL_NOTIFICATION_ACTIVITY_NAME,
        DELETE_MORTAL_SCHEDULE_ACTIVITY_NAME,
        CLEANUP_PAYLOADS_ACTIVITY_NAME,
    ], "historical notification did not reconcile its stale Schedule and payload"


async def test_propagates_historical_preparation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def execute_activity(*_: object, **__: object) -> object:
        raise activity_error()

    subject = MortalNotificationWorkflow()
    monkeypatch.setattr(temporal_workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subject, "_log_failure", lambda *_: None)

    with pytest.raises(ActivityError):
        await subject._prepare(
            mortal_id=370_027,
            response_key="response:3727",
            activity_timeout=datetime.resolution,
        )


async def test_marks_historical_forbidden_delivery_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def execute_activity(name: str, *_: object, **__: object) -> object:
        events.append(name)
        if name == DELIVER_RESPONSE_ACTIVITY_NAME:
            raise activity_error(
                ApplicationError(
                    "recipient blocked the bot",
                    type="TelegramRecipientUnavailable",
                )
            )
        return None

    subject = MortalNotificationWorkflow()
    monkeypatch.setattr(temporal_workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subject, "_log_failure", lambda *_: None)

    actual = await subject._deliver(
        mortal_id=370_031,
        response_key="response:3731",
        activity_timeout=datetime.resolution,
    )

    assert (actual, events) == (
        False,
        [DELIVER_RESPONSE_ACTIVITY_NAME, MARK_MORTAL_UNREACHABLE_ACTIVITY_NAME],
    ), "historical forbidden delivery did not mark its Mortal unreachable"


def test_continues_as_new_with_the_absolute_delivery_deadline_when_suggested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deadline = datetime(2100, 1, 2, 8, 0, tzinfo=UTC)
    original = MortalNotificationWorkflowInput(
        mortal_id=370_003,
        activity_retry_timeout_seconds=300,
    )
    continued: list[MortalNotificationWorkflowInput] = []
    monkeypatch.setattr(
        temporal_workflow,
        "info",
        lambda: SimpleNamespace(is_continue_as_new_suggested=lambda: True),
    )
    monkeypatch.setattr(
        temporal_workflow,
        "continue_as_new",
        continued.append,
    )

    MortalNotificationWorkflow()._continue_as_new_if_suggested(original, deadline)

    assert continued == [
        MortalNotificationWorkflowInput(
            mortal_id=370_003,
            activity_retry_timeout_seconds=300,
            delivery_deadline=deadline.isoformat(),
        )
    ], "Continue-As-New lost or recomputed the absolute delivery deadline"
