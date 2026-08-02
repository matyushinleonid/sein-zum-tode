from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.notifications.custom_schedule.config import (
    MockNotificationScheduleConfig,
)
from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleProposal,
    NotificationScheduleRequest,
)


class MockNotificationScheduleInterpreter:
    def __init__(
        self,
        *,
        config: MockNotificationScheduleConfig,
        content: BotContent,
    ) -> None:
        self._config = config
        self._content = content

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def consumes_quota(self) -> bool:
        return False

    async def interpret(
        self,
        request: NotificationScheduleRequest,
    ) -> NotificationScheduleProposal:
        return NotificationScheduleProposal(
            understood=True,
            cron=self._config.cron,
            timezone=self._config.timezone or request.current_timezone,
            explanation=self._content.localized(request.locale).notification_settings.custom_mock,
        )

    async def close(self) -> None:
        return None
