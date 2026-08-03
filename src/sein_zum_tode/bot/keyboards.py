from dataclasses import dataclass

from aiogram.types import Update

from sein_zum_tode.bot.content import BotContent, LocalizedBotContent
from sein_zum_tode.bot.models import (
    TelegramButton,
    TelegramKeyboardMode,
)
from sein_zum_tode.localization.models import SupportedLocale
from sein_zum_tode.notifications.custom_schedule.config import NotificationPresets
from sein_zum_tode.notifications.custom_schedule.presentation import (
    NotificationPresetPresenter,
)
from sein_zum_tode.notifications.models import (
    CUSTOM_NOTIFICATION_CALLBACK_DATA,
    NotificationFrequency,
)


@dataclass(frozen=True, slots=True)
class TelegramKeyboardSelection:
    data: str
    from_reply_keyboard: bool


class TelegramKeyboardCatalog:
    def __init__(
        self,
        *,
        content: BotContent,
        notification_presets: NotificationPresets,
        mode: TelegramKeyboardMode,
    ) -> None:
        self._content = content
        self._presenter = NotificationPresetPresenter(notification_presets)
        self._mode = mode
        self._reply_selections = self._build_reply_selections()
        self._callback_selections = frozenset(self._reply_selections.values())

    @property
    def mode(self) -> TelegramKeyboardMode:
        return self._mode

    def localization(
        self,
        localized: LocalizedBotContent,
    ) -> tuple[tuple[TelegramButton, ...], ...]:
        settings = localized.localization
        return (
            (
                TelegramButton(
                    text=settings.russian,
                    callback_data=SupportedLocale.RUSSIAN.callback_data(),
                ),
                TelegramButton(
                    text=settings.english,
                    callback_data=SupportedLocale.ENGLISH.callback_data(),
                ),
            ),
        )

    def notifications(
        self,
        localized: LocalizedBotContent,
    ) -> tuple[tuple[TelegramButton, ...], ...]:
        settings = localized.notification_settings
        return (
            (
                self._notification_button(
                    NotificationFrequency.DAILY,
                    settings.daily,
                ),
                self._notification_button(
                    NotificationFrequency.WEEKLY,
                    settings.weekly,
                ),
            ),
            (
                self._notification_button(
                    NotificationFrequency.MONTHLY,
                    settings.monthly,
                ),
                self._notification_button(
                    NotificationFrequency.NEVER,
                    settings.never,
                ),
            ),
            (
                TelegramButton(
                    text=settings.custom,
                    callback_data=CUSTOM_NOTIFICATION_CALLBACK_DATA,
                ),
            ),
        )

    def selection(self, update: Update) -> TelegramKeyboardSelection | None:
        callback = update.callback_query
        if callback is not None and callback.data in self._callback_selections:
            return TelegramKeyboardSelection(
                data=callback.data,
                from_reply_keyboard=False,
            )
        message = update.message
        if message is None or message.text is None:
            return None
        data = self._reply_selections.get(message.text)
        if data is None:
            return None
        return TelegramKeyboardSelection(
            data=data,
            from_reply_keyboard=True,
        )

    def _build_reply_selections(self) -> dict[str, str]:
        selections: dict[str, str] = {}
        for localized in self._content.locales.values():
            for row in self.localization(localized) + self.notifications(localized):
                for button in row:
                    existing = selections.get(button.text)
                    if existing is not None and existing != button.callback_data:
                        raise ValueError(
                            f"Telegram reply keyboard label {button.text!r} is ambiguous"
                        )
                    selections[button.text] = button.callback_data
        return selections

    def _notification_button(
        self,
        frequency: NotificationFrequency,
        text: str,
    ) -> TelegramButton:
        return TelegramButton(
            text=self._presenter.label(frequency, text),
            callback_data=frequency.callback_data(),
        )
