import pytest

from sein_zum_tode.bot.models import TelegramKeyboardMode
from sein_zum_tode.localization.models import SupportedLocale
from sein_zum_tode.notifications.models import NotificationFrequency
from tests.support import BotContents, notification_presets, telegram_keyboards

pytestmark = pytest.mark.fast


def test_rejects_a_reply_label_that_means_different_actions() -> None:
    content = BotContents.debug()
    russian = content.locales["ru"]
    ambiguous_settings = russian.notification_settings.model_copy(update={"daily": "Weekly"})
    ambiguous_content = content.model_copy(
        update={
            "locales": {
                **content.locales,
                "ru": russian.model_copy(update={"notification_settings": ambiguous_settings}),
            }
        }
    )

    with pytest.raises(ValueError, match="reply keyboard label"):
        telegram_keyboards(
            content=ambiguous_content,
            presets=notification_presets(),
            mode=TelegramKeyboardMode.REPLY,
        )


def test_rejects_unknown_values_inside_each_keyboard_callback_namespace() -> None:
    assert (
        SupportedLocale.from_callback_data("localization:de"),
        NotificationFrequency.from_callback_data("notifications:yearly"),
    ) == (None, None), "unknown namespaced callbacks were accepted as keyboard selections"
