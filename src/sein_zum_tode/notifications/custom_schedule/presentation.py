from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from babel.dates import format_datetime
from cronsim import CronSim, CronSimError

from sein_zum_tode.bot.content import TELEGRAM_TEXT_LIMIT, NotificationSettingsContent
from sein_zum_tode.notifications.custom_schedule.config import NotificationPresets
from sein_zum_tode.notifications.custom_schedule.models import NotificationScheduleSettings
from sein_zum_tode.notifications.custom_schedule.ports import CronDescriptionProvider
from sein_zum_tode.notifications.models import NotificationFrequency


class NotificationPresetPresenter:
    def __init__(self, presets: NotificationPresets) -> None:
        self._presets = presets

    def label(self, frequency: NotificationFrequency, text: str) -> str:
        cron = self._presets.cron(frequency)
        if cron is None:
            return text
        fields = cron.split()
        if len(fields) != 5 or not fields[0].isdigit() or not fields[1].isdigit():
            return text
        minute, hour = int(fields[0]), int(fields[1])
        return f"{text} · {hour:02d}:{minute:02d}"


class NotificationSchedulePresenter:
    def __init__(
        self,
        *,
        descriptions: CronDescriptionProvider,
        occurrence_count: int = 3,
    ) -> None:
        self._descriptions = descriptions
        self._occurrence_count = occurrence_count

    def applied(
        self,
        *,
        explanation: str,
        settings: NotificationScheduleSettings,
        locale: str,
        now: datetime,
        content: NotificationSettingsContent,
    ) -> str:
        lines = [
            content.custom_interpretation,
            explanation,
            "",
            content.custom_schedule,
        ]
        cron = settings.cron
        if cron is None:
            lines.extend(
                (
                    content.custom_disabled,
                    f"{content.custom_timezone}: {settings.timezone}",
                    "",
                    content.custom_change_hint,
                )
            )
            return self._fit(lines, explanation_index=1)
        description = self._description(cron, locale, content)
        occurrences = self._occurrences(
            cron,
            settings.timezone,
            locale,
            now,
        )
        lines.extend(
            (
                f"{content.custom_cron}: {cron}",
                f"{content.custom_description}: {description}",
                f"{content.custom_timezone}: {settings.timezone}",
                "",
                content.custom_next_notifications,
            )
        )
        if occurrences:
            lines.extend(f"• {value} ({settings.timezone})" for value in occurrences)
        else:
            lines.append(content.custom_next_notifications_unavailable)
        lines.extend(("", content.custom_change_hint))
        return self._fit(lines, explanation_index=1)

    def unchanged(self, explanation: str, content: NotificationSettingsContent) -> str:
        return self._fit(
            [explanation, "", content.custom_unchanged],
            explanation_index=0,
        )

    def _description(
        self,
        cron: str,
        locale: str,
        content: NotificationSettingsContent,
    ) -> str:
        try:
            return self._descriptions.describe(cron, self._descriptor_locale(locale))
        except Exception:
            return content.custom_description_unavailable

    def _occurrences(
        self,
        cron: str,
        timezone_name: str,
        locale: str,
        now: datetime,
    ) -> tuple[str, ...]:
        try:
            timezone = ZoneInfo(timezone_name)
            simulation = CronSim(cron, now.astimezone(timezone))
            values = tuple(next(simulation) for _ in range(self._occurrence_count))
        except CronSimError, OverflowError, StopIteration, ZoneInfoNotFoundError:
            return ()
        return tuple(
            format_datetime(
                value,
                "EEE, d MMM y, HH:mm",
                tzinfo=timezone,
                locale=locale,
            )
            for value in values
        )

    @staticmethod
    def _descriptor_locale(locale: str) -> str:
        return {"ru": "ru_RU", "en": "en_US"}.get(locale, "en_US")

    @staticmethod
    def _fit(lines: list[str], *, explanation_index: int) -> str:
        without_explanation = list(lines)
        without_explanation[explanation_index] = ""
        available = max(0, TELEGRAM_TEXT_LIMIT - len("\n".join(without_explanation)))
        lines[explanation_index] = lines[explanation_index][:available]
        return "\n".join(lines)[:TELEGRAM_TEXT_LIMIT]
