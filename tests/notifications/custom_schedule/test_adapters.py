from datetime import UTC, datetime

import pytest

from sein_zum_tode.notifications.custom_schedule.config import (
    MockNotificationScheduleConfig,
)
from sein_zum_tode.notifications.custom_schedule.llm import (
    LLMNotificationScheduleInterpreter,
)
from sein_zum_tode.notifications.custom_schedule.mock import (
    MockNotificationScheduleInterpreter,
)
from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleProposal,
    NotificationScheduleRequest,
)
from tests.support import BotContents

pytestmark = pytest.mark.fast


def request(locale: str = "en") -> NotificationScheduleRequest:
    return NotificationScheduleRequest(
        locale=locale,
        current_cron="0 9 * * *",
        current_timezone="Europe/Moscow",
        current_local_datetime=datetime(2026, 8, 1, 15, tzinfo=UTC),
        user_request="Every weekday evening",
    )


class CompletionClientDouble:
    def __init__(self, response: NotificationScheduleProposal) -> None:
        self.response = response
        self.provider_name = "structured-nebula"
        self.consumes_quota = True
        self.events: list[tuple[object, ...]] = []

    async def complete(self, *, user_prompt: str) -> NotificationScheduleProposal:
        self.events.append(("complete", user_prompt))
        return self.response

    async def close(self) -> None:
        self.events.append(("close",))


async def test_llm_adapter_delegates_typed_prompt_and_provider_metadata() -> None:
    expected = NotificationScheduleProposal(
        understood=True,
        cron="0 19 * * 1-5",
        timezone="Europe/Moscow",
        explanation="Weekday evening notifications configured.",
    )
    client = CompletionClientDouble(expected)
    interpreter = LLMNotificationScheduleInterpreter(client=client)

    actual = await interpreter.interpret(request())
    await interpreter.close()

    assert (
        interpreter.provider_name,
        interpreter.consumes_quota,
        actual,
        client.events[-1],
    ) == (
        "structured-nebula",
        True,
        expected,
        ("close",),
    ), "LLM schedule adapter changed the typed result or provider metadata"
    assert "Required language for the explanation field: en" in str(client.events[0][1])


async def test_mock_adapter_returns_a_localized_configured_schedule_without_quota() -> None:
    interpreter = MockNotificationScheduleInterpreter(
        config=MockNotificationScheduleConfig(
            cron="0 12 * * *",
            timezone=None,
        ),
        content=BotContents.debug(),
    )

    actual = await interpreter.interpret(request(locale="ru"))
    await interpreter.close()

    assert (
        interpreter.provider_name,
        interpreter.consumes_quota,
        actual,
    ) == (
        "mock",
        False,
        NotificationScheduleProposal(
            understood=True,
            cron="0 12 * * *",
            timezone="Europe/Moscow",
            explanation="Расписание уведомлений обновлено",
        ),
    )
