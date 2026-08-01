from datetime import UTC, date, datetime

import pytest

from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.activities import (
    PrepareMortalNotificationActivity,
    SystemClock,
)
from sein_zum_tode.notifications.models import (
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
)
from tests.support import BotContents, SilentLogger, TelegramMemory

pytestmark = pytest.mark.fast


class ClockDouble:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class MortalRepositoryDouble:
    def __init__(self, mortal: Mortal | None) -> None:
        self.mortal = mortal
        self.events: list[tuple[object, ...]] = []

    async def ensure(self, mortal_id: int) -> Mortal:
        self.events.append(("ensure", mortal_id))
        return Mortal(id=mortal_id)

    async def get(self, mortal_id: int) -> Mortal | None:
        self.events.append(("get", mortal_id))
        return self.mortal

    async def set_death_date(self, mortal_id: int, death_date: date) -> Mortal:
        self.events.append(("set_death_date", mortal_id, death_date))
        return Mortal(id=mortal_id, death_date=death_date)

    async def set_notification_cron(
        self,
        mortal_id: int,
        cron: str | None,
    ) -> Mortal:
        self.events.append(("set_notification_cron", mortal_id, cron))
        return Mortal(id=mortal_id, notification_cron=cron)

    async def set_locale(self, mortal_id: int, locale: str) -> Mortal:
        self.events.append(("set_locale", mortal_id, locale))
        return Mortal(id=mortal_id, locale=locale)

    async def consume_llm_request(self, mortal_id: int, request_id: str) -> Mortal:
        self.events.append(("consume_llm_request", mortal_id, request_id))
        return Mortal(id=mortal_id, llm_requests_remaining=49)

    async def mark_unreachable(self, mortal_id: int) -> None:
        self.events.append(("mark_unreachable", mortal_id))


def responses() -> TelegramMemory:
    return TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )


@pytest.mark.parametrize(
    "mortal",
    [
        None,
        Mortal(id=340_007),
        Mortal(
            id=340_007,
            notification_cron=None,
            death_date=date(2100, 1, 1),
        ),
        Mortal(
            id=340_007,
            death_date=date(2100, 1, 1),
            telegram_unreachable_at=datetime(2099, 11, 30, tzinfo=UTC),
        ),
    ],
)
async def test_skips_a_notification_without_complete_enabled_preferences(
    mortal: Mortal | None,
) -> None:
    repository = MortalRepositoryDouble(mortal)
    payloads = responses()
    subject = PrepareMortalNotificationActivity(
        mortals=repository,
        responses=payloads.response_documents,
        content=BotContents.debug(),
        response_ttl_seconds=3407,
        clock=ClockDouble(datetime(2099, 12, 1, tzinfo=UTC)),
        logger=SilentLogger(),
    )

    actual = await subject.prepare(
        PrepareMortalNotificationInput(
            mortal_id=340_007,
            response_key="telegram:notification:3407",
        )
    )

    assert (
        actual,
        repository.events,
        payloads.events,
    ) == (
        None,
        [("get", 340_007)],
        [],
    ), "notification was prepared for a missing, incomplete, disabled, or unreachable Mortal"


async def test_prepares_a_localized_countdown_in_redis() -> None:
    mortal = Mortal(
        id=340_019,
        death_date=date(2100, 1, 1),
    )
    repository = MortalRepositoryDouble(mortal)
    payloads = responses()
    subject = PrepareMortalNotificationActivity(
        mortals=repository,
        responses=payloads.response_documents,
        content=BotContents.debug(),
        response_ttl_seconds=3413,
        clock=ClockDouble(datetime(2099, 12, 30, 20, 59, tzinfo=UTC)),
        logger=SilentLogger(),
    )

    actual = await subject.prepare(
        PrepareMortalNotificationInput(
            mortal_id=340_019,
            response_key="telegram:notification:3419",
        )
    )

    assert (
        actual,
        payloads.responses["telegram:notification:3419"].chat_id,
        payloads.responses["telegram:notification:3419"].text,
        payloads.events[0][-1],
    ) == (
        PreparedMortalNotification(
            response_key="telegram:notification:3419",
            days_left=2,
        ),
        340_019,
        "mock notification: 2",
        3413,
    ), "notification preparation used the wrong local day, recipient, text, or Redis TTL"


def test_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().utcoffset() is not None, (
        "production notification clock returned a naive timestamp"
    )


@pytest.mark.parametrize(
    ("days_left", "expected"),
    [
        (1, False),
        (0, True),
    ],
)
def test_marks_only_death_day_as_terminal(days_left: int, expected: bool) -> None:
    notification = PreparedMortalNotification(
        response_key="telegram:notification:3433",
        days_left=days_left,
    )

    assert notification.terminal() is expected
