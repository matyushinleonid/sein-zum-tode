from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleProposal,
    NotificationScheduleRequest,
)
from sein_zum_tode.ports.completion import CompletionClient


class LLMNotificationScheduleInterpreter:
    def __init__(
        self,
        *,
        client: CompletionClient[NotificationScheduleProposal],
    ) -> None:
        self._client = client

    @property
    def provider_name(self) -> str:
        return self._client.provider_name

    @property
    def consumes_quota(self) -> bool:
        return self._client.consumes_quota

    async def interpret(
        self,
        request: NotificationScheduleRequest,
    ) -> NotificationScheduleProposal:
        return await self._client.complete(user_prompt=request.prompt())

    async def close(self) -> None:
        await self._client.close()
