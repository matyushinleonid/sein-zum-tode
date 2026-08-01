from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cronsim import CronSim, CronSimError

from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleSettings,
)


class InvalidNotificationScheduleError(ValueError):
    pass


class NotificationScheduleTooFrequentError(ValueError):
    pass


class NotificationScheduleValidator:
    def __init__(self, *, minimum_interval: timedelta) -> None:
        self._minimum_interval = minimum_interval

    def validate(
        self,
        settings: NotificationScheduleSettings,
        *,
        now: datetime,
    ) -> None:
        if now.utcoffset() is None:
            raise ValueError("now must include timezone information")
        try:
            timezone = ZoneInfo(settings.timezone)
        except ZoneInfoNotFoundError as error:
            raise InvalidNotificationScheduleError("notification timezone is invalid") from error
        if settings.cron is None:
            return
        if len(settings.cron.split()) != 5:
            raise InvalidNotificationScheduleError("notification cron must contain five fields")
        try:
            simulation = CronSim(settings.cron, now.astimezone(timezone))
            occurrences = tuple(next(simulation) for _ in range(64))
        except (CronSimError, OverflowError, StopIteration) as error:
            raise InvalidNotificationScheduleError("notification cron is invalid") from error
        intervals = tuple(
            current.astimezone(UTC) - previous.astimezone(UTC)
            for previous, current in zip(occurrences, occurrences[1:], strict=False)
        )
        if intervals and min(intervals) < self._minimum_interval:
            raise NotificationScheduleTooFrequentError("notification cron runs too frequently")
