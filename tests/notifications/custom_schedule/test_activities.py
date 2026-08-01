from datetime import UTC, datetime, timedelta

import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.infrastructure.clock import SystemClock
from sein_zum_tode.mortals.models import Mortal
from sein_zum_tode.notifications.custom_schedule.activities import (
    ApplyCustomNotificationScheduleActivity,
    GenerateCustomNotificationScheduleActivity,
    PrepareCustomNotificationFailureActivity,
)
from sein_zum_tode.notifications.custom_schedule.models import (
    ApplyCustomNotificationScheduleInput,
    CronChange,
    CronOperation,
    GenerateCustomNotificationScheduleInput,
    NotificationScheduleProposal,
    NotificationScheduleRequest,
    PrepareCustomNotificationFailureInput,
    StoredNotificationScheduleProposal,
    TimezoneChange,
    TimezoneOperation,
)
from sein_zum_tode.notifications.custom_schedule.validation import (
    NotificationScheduleValidator,
)
from tests.support import (
    BotContents,
    MortalMemory,
    MortalScheduleMemory,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
    mortal,
)

pytestmark = pytest.mark.fast


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 1, 12, 7, tzinfo=UTC)


class InterpreterDouble:
    def __init__(
        self,
        *,
        proposal: NotificationScheduleProposal,
        consumes_quota: bool,
    ) -> None:
        self.proposal = proposal
        self.consumes_quota = consumes_quota
        self.provider_name = "yandex" if consumes_quota else "mock"
        self.requests: list[NotificationScheduleRequest] = []

    async def interpret(
        self,
        request: NotificationScheduleRequest,
    ) -> NotificationScheduleProposal:
        self.requests.append(request)
        return self.proposal

    async def close(self) -> None:
        return None


class ProposalMemory:
    def __init__(
        self,
        proposals: dict[str, StoredNotificationScheduleProposal] | None = None,
    ) -> None:
        self.proposals = dict(proposals or {})
        self.events: list[tuple[object, ...]] = []

    async def load(self, key: str) -> StoredNotificationScheduleProposal | None:
        self.events.append(("load", key))
        return self.proposals.get(key)

    async def store(
        self,
        key: str,
        document: StoredNotificationScheduleProposal,
        ttl_seconds: int,
    ) -> None:
        self.events.append(("store", key, document, ttl_seconds))
        self.proposals[key] = document


def accepted_proposal(
    *,
    cron: str = "30 19 * * 1-5",
    timezone: str | None = None,
) -> NotificationScheduleProposal:
    return NotificationScheduleProposal(
        understood=True,
        cron=CronChange(operation=CronOperation.SET, value=cron),
        timezone=TimezoneChange(
            operation=(TimezoneOperation.SET if timezone is not None else TimezoneOperation.KEEP),
            value=timezone,
        ),
        message="Расписание настроено.",
    )


def stored_proposal(
    proposal: NotificationScheduleProposal,
) -> StoredNotificationScheduleProposal:
    return StoredNotificationScheduleProposal(
        request_id="request-irregular-4111",
        provider="yandex",
        consumes_quota=True,
        proposal=proposal,
    )


def telegram(update: object = None) -> TelegramMemory:
    return TelegramMemory(
        update_result=update,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )


async def test_generates_once_with_locale_local_time_and_idempotent_global_quota() -> None:
    user_id = 411_017
    update_key = "telegram:update:4111"
    proposal_key = f"{update_key}:notification-schedule"
    payloads = telegram(
        TelegramUpdates.message(
            update_id=4111,
            user_id=user_id,
            chat_id=user_id,
            text="По будням вечером",
            chat_type="private",
        )
    )
    proposals = ProposalMemory()
    mortals = MortalMemory(
        {
            user_id: mortal(
                id=user_id,
                locale="ru",
                timezone="Europe/Moscow",
            )
        }
    )
    interpreter = InterpreterDouble(
        proposal=accepted_proposal(),
        consumes_quota=True,
    )
    subject = GenerateCustomNotificationScheduleActivity(
        interpreter=interpreter,
        proposals=proposals,
        updates=payloads.update_documents,
        mortals=mortals,
        default_locale="en",
        ttl_seconds=4117,
        clock=FixedClock(),
        logger=SilentLogger(),
    )
    input = GenerateCustomNotificationScheduleInput(
        update_key=update_key,
        proposal_key=proposal_key,
        user_id=user_id,
    )

    await subject.generate(input)
    await subject.generate(input)

    request = interpreter.requests[0]
    assert (
        len(interpreter.requests),
        request.locale,
        request.current_local_datetime.isoformat(),
        request.user_request,
        mortals.mortals[user_id].llm_requests_remaining,
        proposals.events[1][0],
        proposals.events[1][-1],
    ) == (
        1,
        "ru",
        "2026-08-01T15:07:00+03:00",
        "По будням вечером",
        49,
        "store",
        4117,
    ), "generation repeated completion or lost locale, timezone, input, TTL, or quota"


@pytest.mark.parametrize(
    ("has_update", "has_mortal"),
    [(False, True), (True, False)],
)
async def test_rejects_expired_custom_schedule_input(
    has_update: bool,
    has_mortal: bool,
) -> None:
    user_id = 412_013
    update = (
        TelegramUpdates.message(
            update_id=4121,
            user_id=user_id,
            chat_id=user_id,
            text="At noon",
            chat_type="private",
        )
        if has_update
        else None
    )
    subject = GenerateCustomNotificationScheduleActivity(
        interpreter=InterpreterDouble(
            proposal=accepted_proposal(),
            consumes_quota=False,
        ),
        proposals=ProposalMemory(),
        updates=telegram(update).update_documents,
        mortals=MortalMemory({user_id: mortal(id=user_id)} if has_mortal else {}),
        default_locale="en",
        ttl_seconds=4127,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.generate(
            GenerateCustomNotificationScheduleInput(
                update_key="telegram:update:4121",
                proposal_key="telegram:update:4121:notification-schedule",
                user_id=user_id,
            )
        )


async def test_applies_cron_timezone_schedule_and_model_message() -> None:
    user_id = 413_017
    proposal_key = "telegram:update:4131:notification-schedule"
    proposal = accepted_proposal(timezone="Europe/Berlin")
    proposals = ProposalMemory({proposal_key: stored_proposal(proposal)})
    payloads = telegram()
    mortals = MortalMemory({user_id: mortal(id=user_id, locale="ru")})
    schedules = MortalScheduleMemory()
    subject = ApplyCustomNotificationScheduleActivity(
        proposals=proposals,
        responses=payloads.response_documents,
        mortals=mortals,
        schedules=schedules,
        validator=NotificationScheduleValidator(minimum_interval=timedelta(hours=20)),
        content=BotContents.debug(),
        response_ttl_seconds=4133,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    await subject.apply(
        ApplyCustomNotificationScheduleInput(
            proposal_key=proposal_key,
            response_key="telegram:update:4131:response",
            user_id=user_id,
            chat_id=user_id,
        )
    )

    current_mortal = mortals.mortals[user_id]
    assert (
        current_mortal.notification_cron,
        current_mortal.timezone,
        schedules.events,
        payloads.responses["telegram:update:4131:response"].text,
    ) == (
        "30 19 * * 1-5",
        "Europe/Berlin",
        [("ensure", current_mortal)],
        "Расписание настроено.",
    ), "valid proposal did not atomically update PostgreSQL, Schedule, and response"


async def test_returns_a_model_rejection_without_changing_preferences() -> None:
    user_id = 413_039
    proposal_key = "telegram:update:4139:notification-schedule"
    proposal = NotificationScheduleProposal(
        understood=False,
        cron=CronChange(operation=CronOperation.KEEP),
        timezone=TimezoneChange(operation=TimezoneOperation.KEEP),
        message="Please describe a time and frequency.",
    )
    original = mortal(id=user_id, locale="en")
    proposals = ProposalMemory({proposal_key: stored_proposal(proposal)})
    payloads = telegram()
    mortals = MortalMemory({user_id: original})
    schedules = MortalScheduleMemory()
    subject = ApplyCustomNotificationScheduleActivity(
        proposals=proposals,
        responses=payloads.response_documents,
        mortals=mortals,
        schedules=schedules,
        validator=NotificationScheduleValidator(minimum_interval=timedelta(hours=20)),
        content=BotContents.debug(),
        response_ttl_seconds=4141,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    await subject.apply(
        ApplyCustomNotificationScheduleInput(
            proposal_key=proposal_key,
            response_key="telegram:update:4139:response",
            user_id=user_id,
            chat_id=user_id,
        )
    )

    assert (
        mortals.mortals[user_id],
        schedules.events,
        payloads.responses["telegram:update:4139:response"].text,
    ) == (
        original,
        [],
        "Please describe a time and frequency.",
    )


@pytest.mark.parametrize(
    ("cron", "expected"),
    [
        ("invalid", "Custom notification schedule is invalid"),
        ("0 */2 * * *", "Notifications cannot be sent more than daily"),
    ],
)
async def test_localizes_invalid_or_excessively_frequent_proposals(
    cron: str,
    expected: str,
) -> None:
    user_id = 415_019
    proposal_key = "telegram:update:4151:notification-schedule"
    proposals = ProposalMemory({proposal_key: stored_proposal(accepted_proposal(cron=cron))})
    payloads = telegram()
    mortals = MortalMemory({user_id: mortal(id=user_id, locale="en")})
    schedules = MortalScheduleMemory()
    subject = ApplyCustomNotificationScheduleActivity(
        proposals=proposals,
        responses=payloads.response_documents,
        mortals=mortals,
        schedules=schedules,
        validator=NotificationScheduleValidator(minimum_interval=timedelta(hours=20)),
        content=BotContents.debug(),
        response_ttl_seconds=4153,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    await subject.apply(
        ApplyCustomNotificationScheduleInput(
            proposal_key=proposal_key,
            response_key="telegram:update:4151:response",
            user_id=user_id,
            chat_id=user_id,
        )
    )

    assert (
        mortals.mortals[user_id].notification_cron,
        schedules.events,
        payloads.responses["telegram:update:4151:response"].text,
    ) == (
        "0 9 * * *",
        [],
        expected,
    )


@pytest.mark.parametrize(
    ("has_proposal", "has_mortal"),
    [(False, True), (True, False)],
)
async def test_rejects_expired_custom_schedule_proposals(
    has_proposal: bool,
    has_mortal: bool,
) -> None:
    user_id = 416_011
    proposal_key = "telegram:update:4161:notification-schedule"
    proposals = ProposalMemory(
        {proposal_key: stored_proposal(accepted_proposal())} if has_proposal else {}
    )
    subject = ApplyCustomNotificationScheduleActivity(
        proposals=proposals,
        responses=telegram().response_documents,
        mortals=MortalMemory({user_id: mortal(id=user_id)} if has_mortal else {}),
        schedules=MortalScheduleMemory(),
        validator=NotificationScheduleValidator(minimum_interval=timedelta(hours=20)),
        content=BotContents.debug(),
        response_ttl_seconds=4163,
        clock=FixedClock(),
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.apply(
            ApplyCustomNotificationScheduleInput(
                proposal_key=proposal_key,
                response_key="telegram:update:4161:response",
                user_id=user_id,
                chat_id=user_id,
            )
        )


@pytest.mark.parametrize(
    ("mortal", "expected"),
    [
        (None, "Custom notification schedule failed"),
        (
            mortal(id=417_019, locale="ru"),
            "Не удалось настроить расписание уведомлений",
        ),
    ],
)
async def test_prepares_a_localized_failure_response(
    mortal: Mortal | None,
    expected: str,
) -> None:
    user_id = 417_019
    payloads = telegram()
    subject = PrepareCustomNotificationFailureActivity(
        mortals=MortalMemory({user_id: mortal} if mortal is not None else {}),
        responses=payloads.response_documents,
        content=BotContents.debug(),
        response_ttl_seconds=4177,
    )

    await subject.prepare(
        PrepareCustomNotificationFailureInput(
            response_key="telegram:update:4171:response",
            user_id=user_id,
            chat_id=user_id,
        )
    )

    assert payloads.responses["telegram:update:4171:response"].text == expected


def test_custom_schedule_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().utcoffset() is not None
