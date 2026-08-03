import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.models import PrepareResponseInput
from sein_zum_tode.notifications.custom_schedule.config import NotificationPresets
from sein_zum_tode.notifications.settings import ConfigureMortalNotificationsActivity
from tests.support import (
    BotContents,
    MortalMemory,
    MortalScheduleMemory,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
    mortal,
    notification_presets,
    telegram_keyboards,
)

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("frequency", "cron", "label"),
    [
        ("daily", "17 8 * * *", "Daily"),
        ("weekly", "19 9 * * 2", "Weekly"),
        ("monthly", "23 10 3 * *", "Monthly"),
        ("never", None, "Never"),
    ],
)
async def test_configures_each_notification_frequency(
    frequency: str,
    cron: str | None,
    label: str,
) -> None:
    user_id = 351_017
    payloads = TelegramMemory(
        update_result=TelegramUpdates.callback(
            update_id=3511,
            user_id=user_id,
            chat_id=user_id,
            chat_type="private",
            data=f"notifications:{frequency}",
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    mortals = MortalMemory({user_id: mortal(id=user_id)})
    schedules = MortalScheduleMemory()
    subject = ConfigureMortalNotificationsActivity(
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=mortals,
        schedules=schedules,
        content=BotContents.debug(),
        presets=NotificationPresets(
            daily="17 8 * * *",
            weekly="19 9 * * 2",
            monthly="23 10 3 * *",
            never=None,
        ),
        keyboards=telegram_keyboards(),
        response_ttl_seconds=3517,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:callback:3511",
        response_key="telegram:callback:3511:response",
        chat_id=user_id,
        user_id=user_id,
        callback_query_id="callback-Sphinx-915",
    )

    await subject.configure(input)

    response = payloads.responses[input.response_key]
    assert (
        mortals.mortals[user_id].notification_cron,
        schedules.events,
        response.text,
        response.callback_query_id,
    ) == (
        cron,
        [("ensure", mortals.mortals[user_id])],
        f"Notifications: {label}",
        "callback-Sphinx-915",
    ), "callback selection did not update PostgreSQL, Schedule, or localized response"


async def test_configures_notifications_from_reply_keyboard_text() -> None:
    user_id = 351_019
    payloads = TelegramMemory(
        update_result=TelegramUpdates.message(
            update_id=3519,
            user_id=user_id,
            chat_id=user_id,
            text="Weekly · 09:00",
            chat_type="private",
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    mortals = MortalMemory({user_id: mortal(id=user_id)})
    schedules = MortalScheduleMemory()
    presets = notification_presets()
    subject = ConfigureMortalNotificationsActivity(
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=mortals,
        schedules=schedules,
        content=BotContents.debug(),
        presets=presets,
        keyboards=telegram_keyboards(presets=presets),
        response_ttl_seconds=3521,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:notifications:3519",
        response_key="telegram:notifications:3519:response",
        chat_id=user_id,
        user_id=user_id,
        remove_reply_keyboard=True,
    )

    await subject.configure(input)

    response = payloads.responses[input.response_key]
    assert (
        mortals.mortals[user_id].notification_cron,
        response.text,
        response.remove_reply_keyboard,
    ) == (
        "0 9 * * 1",
        "Notifications: Weekly",
        True,
    ), "reply keyboard frequency was not persisted, confirmed, and dismissed"


async def test_rejects_an_unknown_notification_callback() -> None:
    payloads = TelegramMemory(
        update_result=TelegramUpdates.callback(
            update_id=3527,
            user_id=352_729,
            chat_id=352_729,
            chat_type="private",
            data="notifications:yearly",
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    subject = ConfigureMortalNotificationsActivity(
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=MortalMemory(),
        schedules=MortalScheduleMemory(),
        content=BotContents.debug(),
        presets=NotificationPresets(
            daily="17 8 * * *",
            weekly="19 9 * * 2",
            monthly="23 10 3 * *",
            never=None,
        ),
        keyboards=telegram_keyboards(),
        response_ttl_seconds=3529,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.configure(
            PrepareResponseInput(
                update_key="telegram:callback:3527",
                response_key="telegram:callback:3527:response",
                chat_id=352_729,
                user_id=352_729,
            )
        )


def test_rejects_callback_data_outside_the_notification_namespace() -> None:
    from sein_zum_tode.notifications.models import NotificationFrequency

    assert (
        NotificationFrequency.from_callback_data(None),
        NotificationFrequency.from_callback_data("another:daily"),
    ) == (None, None)
