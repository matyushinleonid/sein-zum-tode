from collections.abc import Awaitable
from typing import Protocol

from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleProposal,
    NotificationScheduleRequest,
)


class NotificationScheduleInterpreter(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def consumes_quota(self) -> bool: ...

    def interpret(
        self,
        request: NotificationScheduleRequest,
    ) -> Awaitable[NotificationScheduleProposal]: ...

    def close(self) -> Awaitable[None]: ...


class CronDescriptionProvider(Protocol):
    def describe(self, expression: str, locale: str) -> str: ...
