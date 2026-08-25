from datetime import UTC, date, datetime

import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.content import NotificationTier
from sein_zum_tode.bot.models import (
    PrepareResponseInput,
    TelegramAttachment,
    TelegramAttachmentKind,
    TelegramResponse,
)
from sein_zum_tode.infrastructure.clock import SystemClock
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.activities import (
    PlanMortalNotificationDeliveryActivity,
    PrepareMortalNotificationActivity,
    PrepareNotificationSampleActivity,
)
from sein_zum_tode.notifications.models import (
    MortalNotificationDeliveryPlan,
    PlanMortalNotificationDeliveryInput,
    PreparedMortalNotification,
    PrepareMortalNotificationInput,
    RenderedNotification,
)
from sein_zum_tode.notifications.presentation import NotificationMessagePresenter
from tests.support import BotContents, NumberSpellerMemory, SilentLogger, TelegramMemory, mortal

pytestmark = pytest.mark.fast


class ClockDouble:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class MortalRepositoryDouble:
    def __init__(self, mortal: Mortal | None) -> None:
        self.mortal = mortal
        self.events: list[tuple[object, ...]] = []

    async def ensure(self, mortal_id: int) -> Mortal:
        self.events.append(("ensure", mortal_id))
        return mortal(id=mortal_id)

    async def get(self, mortal_id: int) -> Mortal | None:
        self.events.append(("get", mortal_id))
        return self.mortal

    async def set_death_date(self, mortal_id: int, death_date: date) -> Mortal:
        self.events.append(("set_death_date", mortal_id, death_date))
        return mortal(id=mortal_id, death_date=death_date)

    async def set_notification_cron(
        self,
        mortal_id: int,
        cron: str | None,
    ) -> Mortal:
        self.events.append(("set_notification_cron", mortal_id, cron))
        return mortal(id=mortal_id, notification_cron=cron)

    async def set_notification_settings(
        self,
        mortal_id: int,
        *,
        cron: str | None,
        timezone: str,
    ) -> Mortal:
        self.events.append(("set_notification_settings", mortal_id, cron, timezone))
        return mortal(id=mortal_id, notification_cron=cron, timezone=timezone)

    async def set_locale(self, mortal_id: int, locale: str) -> Mortal:
        self.events.append(("set_locale", mortal_id, locale))
        return mortal(id=mortal_id, locale=locale)

    async def consume_llm_request(self, mortal_id: int, request_id: str) -> Mortal:
        self.events.append(("consume_llm_request", mortal_id, request_id))
        return mortal(id=mortal_id, llm_requests_remaining=14)

    async def mark_unreachable(self, mortal_id: int) -> None:
        self.events.append(("mark_unreachable", mortal_id))


class NotificationPresenterMemory:
    def __init__(self, rendered: RenderedNotification) -> None:
        self.rendered = rendered
        self.events: list[tuple[object, ...]] = []

    def render(
        self,
        *,
        locale: str | None,
        days_left: int,
        seed: str,
        today: date | None = None,
        death_date: date | None = None,
        sample: NotificationTier | None = None,
    ) -> RenderedNotification:
        self.events.append((locale, days_left, seed, sample))
        return self.rendered


class MortalScheduleDouble:
    def __init__(self, next_action_time: datetime | None) -> None:
        self.next_action = next_action_time
        self.events: list[tuple[object, ...]] = []

    async def ensure(self, mortal: Mortal) -> None:
        self.events.append(("ensure", mortal.id))

    async def delete(self, mortal_id: int) -> None:
        self.events.append(("delete", mortal_id))

    async def next_action_time(self, mortal_id: int) -> datetime | None:
        self.events.append(("next_action_time", mortal_id))
        return self.next_action


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
        mortal(id=340_007),
        mortal(
            id=340_007,
            notification_cron=None,
            death_date=date(2100, 1, 1),
        ),
        mortal(
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
        presenter=NotificationMessagePresenter(
            content=BotContents.debug(),
            number_speller=NumberSpellerMemory(words={}),
        ),
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
    current_mortal = mortal(
        id=340_019,
        death_date=date(2100, 1, 1),
    )
    repository = MortalRepositoryDouble(current_mortal)
    payloads = responses()
    clock = ClockDouble(datetime(2099, 12, 30, 20, 59, tzinfo=UTC))
    subject = PrepareMortalNotificationActivity(
        mortals=repository,
        responses=payloads.response_documents,
        presenter=NotificationMessagePresenter(
            content=BotContents.debug(),
            number_speller=NumberSpellerMemory(words={}),
        ),
        clock=clock,
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
        clock.calls,
    ) == (
        PreparedMortalNotification(
            response_key="telegram:notification:3419",
            days_left=2,
        ),
        340_019,
        "mock notification: 2",
        60,
        1,
    ), "notification preparation used the wrong local day, recipient, text, or Redis TTL"


async def test_plans_delivery_until_one_hour_before_the_next_schedule_action() -> None:
    next_action = datetime(2100, 1, 2, 9, 0, tzinfo=UTC)
    schedules = MortalScheduleDouble(next_action)
    subject = PlanMortalNotificationDeliveryActivity(
        schedules=schedules,
        deadline_margin_seconds=3600,
    )

    actual = await subject.plan(
        PlanMortalNotificationDeliveryInput(mortal_id=340_023),
    )

    assert (
        actual,
        schedules.events,
    ) == (
        MortalNotificationDeliveryPlan.ending_at(
            datetime(2100, 1, 2, 8, 0, tzinfo=UTC),
        ),
        [("next_action_time", 340_023)],
    ), "delivery deadline ignored the next Schedule action or its safety margin"


async def test_returns_no_delivery_plan_without_a_future_schedule_action() -> None:
    schedules = MortalScheduleDouble(None)
    subject = PlanMortalNotificationDeliveryActivity(
        schedules=schedules,
        deadline_margin_seconds=3600,
    )

    actual = await subject.plan(
        PlanMortalNotificationDeliveryInput(mortal_id=340_027),
    )

    assert (
        actual,
        schedules.events,
    ) == (
        None,
        [("next_action_time", 340_027)],
    ), "planner invented a delivery window without a future Schedule action"


async def test_prepares_an_admin_notification_sample_with_its_reward_payload() -> None:
    repository = MortalRepositoryDouble(
        mortal(
            id=162573173,
            locale="ru",
            death_date=date(2100, 1, 1),
        )
    )
    payloads = responses()
    rendered = RenderedNotification(
        text="rare emoji\nОсталось 2 дня",
        parse_mode="HTML",
        fallback_text="💀⬅️🚶\nОсталось 2 дня",
        prelude_text="👑 Mythic!",
        attachment=TelegramAttachment(
            kind=TelegramAttachmentKind.AUDIO,
            url="https://example.com/stupa.mp3",
        ),
        variant_id="stupa",
        tier=NotificationTier.MYTHIC,
    )
    presenter = NotificationPresenterMemory(rendered)
    clock = ClockDouble(datetime(2099, 12, 30, 20, 59, tzinfo=UTC))
    subject = PrepareNotificationSampleActivity(
        mortals=repository,
        responses=payloads.response_documents,
        presenter=presenter,
        content=BotContents.debug(),
        response_ttl_seconds=3421,
        clock=clock,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:sample:3421",
        response_key="telegram:sample:3421:response",
        chat_id=162573173,
        user_id=162573173,
        notification_sample=NotificationTier.MYTHIC,
    )

    await subject.prepare(input)

    assert (
        presenter.events,
        payloads.responses[input.response_key],
        payloads.events[0][-1],
        clock.calls,
    ) == (
        [("ru", 2, input.response_key, NotificationTier.MYTHIC)],
        TelegramResponse(
            chat_id=162573173,
            text=rendered.text,
            parse_mode=rendered.parse_mode,
            fallback_text=rendered.fallback_text,
            prelude_text=rendered.prelude_text,
            attachment=rendered.attachment,
        ),
        3421,
        1,
    ), "admin sample lost its forced tier, countdown, prelude, media, or response TTL"


async def test_falls_back_to_help_when_an_admin_has_no_death_prediction() -> None:
    repository = MortalRepositoryDouble(mortal(id=162573173, locale="ru"))
    payloads = responses()
    presenter = NotificationPresenterMemory(
        RenderedNotification(
            text="unused",
            parse_mode=None,
            fallback_text=None,
            prelude_text=None,
            attachment=None,
            variant_id="unused",
            tier=None,
        )
    )
    subject = PrepareNotificationSampleActivity(
        mortals=repository,
        responses=payloads.response_documents,
        presenter=presenter,
        content=BotContents.debug(),
        response_ttl_seconds=3433,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:sample:3433",
        response_key="telegram:sample:3433:response",
        chat_id=162573173,
        user_id=162573173,
        notification_sample=NotificationTier.LUCKY,
    )

    await subject.prepare(input)

    assert (
        presenter.events,
        payloads.responses[input.response_key],
    ) == (
        [],
        TelegramResponse(
            chat_id=162573173,
            text="Нажмите /help, чтобы узнать, как пользоваться ботом.",
        ),
    ), "sample without days_left did not behave like ordinary text outside questionnaire"


async def test_rejects_a_notification_sample_without_a_tier() -> None:
    subject = PrepareNotificationSampleActivity(
        mortals=MortalRepositoryDouble(mortal(id=162573173)),
        responses=responses().response_documents,
        presenter=NotificationPresenterMemory(
            RenderedNotification(
                text="unused",
                parse_mode=None,
                fallback_text=None,
                prelude_text=None,
                attachment=None,
                variant_id="unused",
                tier=None,
            )
        ),
        content=BotContents.debug(),
        response_ttl_seconds=3449,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.prepare(
            PrepareResponseInput(
                update_key="telegram:sample:missing-tier",
                response_key="telegram:sample:missing-tier:response",
                chat_id=162573173,
                user_id=162573173,
            )
        )


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
