import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.models import PrepareResponseInput
from sein_zum_tode.localization.models import SupportedLocale
from sein_zum_tode.localization.settings import ConfigureMortalLocalizationActivity
from sein_zum_tode.mortals.models import Mortal
from tests.support import (
    BotContents,
    MortalMemory,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
)

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("locale", "confirmation"),
    [
        ("ru", "Язык изменён на русский."),
        ("en", "Language changed to English."),
    ],
)
async def test_configures_each_supported_localization(
    locale: str,
    confirmation: str,
) -> None:
    user_id = 361_013
    payloads = TelegramMemory(
        update_result=TelegramUpdates.callback(
            update_id=3611,
            user_id=user_id,
            chat_id=user_id,
            chat_type="private",
            data=f"localization:{locale}",
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    mortals = MortalMemory({user_id: Mortal(id=user_id)})
    subject = ConfigureMortalLocalizationActivity(
        updates=payloads,
        responses=payloads,
        mortals=mortals,
        content=BotContents.debug(),
        response_ttl_seconds=3617,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:localization:3611",
        response_key="telegram:localization:3611:response",
        chat_id=user_id,
        user_id=user_id,
        callback_query_id="callback-Sphinx-915",
    )

    await subject.configure(input)

    response = payloads.responses[input.response_key]
    assert (
        mortals.mortals[user_id].locale,
        response.text,
        response.callback_query_id,
    ) == (
        locale,
        confirmation,
        "callback-Sphinx-915",
    ), "localization callback did not persist or confirm the selected language"


@pytest.mark.parametrize(
    "callback_data",
    [
        None,
        "notifications:daily",
        "localization:de",
    ],
)
async def test_rejects_an_invalid_localization_callback(
    callback_data: str | None,
) -> None:
    user_id = 361_019
    payloads = TelegramMemory(
        update_result=TelegramUpdates.callback(
            update_id=3619,
            user_id=user_id,
            chat_id=user_id,
            chat_type="private",
            data=callback_data,
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    subject = ConfigureMortalLocalizationActivity(
        updates=payloads,
        responses=payloads,
        mortals=MortalMemory(),
        content=BotContents.debug(),
        response_ttl_seconds=3623,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.configure(
            PrepareResponseInput(
                update_key="telegram:localization:3619",
                response_key="telegram:localization:3619:response",
                chat_id=user_id,
                user_id=user_id,
            )
        )


def test_rejects_callback_data_outside_the_localization_namespace() -> None:
    assert (
        SupportedLocale.from_callback_data(None),
        SupportedLocale.from_callback_data("notifications:daily"),
    ) == (None, None)
