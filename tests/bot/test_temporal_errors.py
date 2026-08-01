import pytest
from temporalio.exceptions import ActivityError, ApplicationError

from sein_zum_tode.bot.temporal_errors import (
    TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE,
    is_telegram_recipient_unavailable,
)

pytestmark = pytest.mark.fast


def activity_error(cause: BaseException | None) -> ActivityError:
    error = ActivityError(
        "delivery failed",
        scheduled_event_id=4801,
        started_event_id=4803,
        identity="worker-4807",
        activity_type="deliver",
        activity_id="activity-4813",
        retry_state=None,
    )
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (
            ApplicationError(
                "blocked",
                type=TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE,
            ),
            True,
        ),
        (ApplicationError("rejected", type="PermanentTelegramDeliveryError"), False),
        (None, False),
    ],
)
def test_recognizes_only_the_recipient_unavailable_temporal_contract(
    cause: BaseException | None,
    expected: bool,
) -> None:
    assert is_telegram_recipient_unavailable(activity_error(cause)) is expected
