import pytest
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.models import PrepareResponseInput, TelegramResponse
from sein_zum_tode.localization.models import SupportedLocale
from sein_zum_tode.localization.settings import ConfigureMortalLocalizationActivity
from tests.support import (
    BotContents,
    MortalMemory,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
    mortal,
    telegram_keyboards,
)

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(
    ("locale", "confirmation", "help_text"),
    [
        ("ru", "Язык изменён на русский.", "Путь укажут созвездия"),
        ("en", "Language changed to English.", "Navigate by the constellations"),
    ],
)
async def test_onboards_a_first_time_mortal_with_help_after_the_confirmation(
    locale: str,
    confirmation: str,
    help_text: str,
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
    mortals = MortalMemory({user_id: mortal(id=user_id)})
    subject = ConfigureMortalLocalizationActivity(
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=mortals,
        content=BotContents.debug(),
        keyboards=telegram_keyboards(),
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
        response.prelude_text,
        response.text,
        response.callback_query_id,
    ) == (
        locale,
        confirmation,
        help_text,
        "callback-Sphinx-915",
    ), "first language choice did not persist, confirm, and then onboard with help"


async def test_confirms_a_later_language_change_without_repeating_help() -> None:
    user_id = 361_027
    payloads = TelegramMemory(
        update_result=TelegramUpdates.callback(
            update_id=3623,
            user_id=user_id,
            chat_id=user_id,
            chat_type="private",
            data="localization:en",
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    mortals = MortalMemory({user_id: mortal(id=user_id, locale="ru")})
    subject = ConfigureMortalLocalizationActivity(
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=mortals,
        content=BotContents.debug(),
        keyboards=telegram_keyboards(),
        response_ttl_seconds=3631,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:localization:3623",
        response_key="telegram:localization:3623:response",
        chat_id=user_id,
        user_id=user_id,
    )

    await subject.configure(input)

    response = payloads.responses[input.response_key]
    assert (
        mortals.mortals[user_id].locale,
        response.prelude_text,
        response.text,
    ) == (
        "en",
        None,
        "Language changed to English.",
    ), "a returning mortal was onboarded again instead of only confirming the switch"


async def test_reuses_the_onboarding_response_after_locale_persistence_is_replayed() -> None:
    user_id = 361_031
    response_key = "telegram:localization:retry:response"
    prepared = TelegramResponse(
        chat_id=user_id,
        text="Navigate by the constellations",
        prelude_text="Language changed to English.",
        callback_query_id="callback-retry-361",
    )
    payloads = TelegramMemory(
        update_result=TelegramUpdates.callback(
            update_id=3629,
            user_id=user_id,
            chat_id=user_id,
            chat_type="private",
            data="localization:en",
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    payloads.responses[response_key] = prepared
    mortals = MortalMemory({user_id: mortal(id=user_id, locale="en")})
    subject = ConfigureMortalLocalizationActivity(
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=mortals,
        content=BotContents.debug(),
        keyboards=telegram_keyboards(),
        response_ttl_seconds=3637,
        logger=SilentLogger(),
    )

    await subject.configure(
        PrepareResponseInput(
            update_key="telegram:localization:retry",
            response_key=response_key,
            chat_id=user_id,
            user_id=user_id,
            callback_query_id="callback-retry-361",
        )
    )

    assert (payloads.responses[response_key], mortals.events) == (
        prepared,
        [("set_locale", user_id, "en")],
    ), "Activity retry replaced the prepared onboarding help after locale persistence"


async def test_configures_localization_from_reply_keyboard_text() -> None:
    user_id = 361_017
    payloads = TelegramMemory(
        update_result=TelegramUpdates.message(
            update_id=3617,
            user_id=user_id,
            chat_id=user_id,
            text="🇷🇺 RU",
            chat_type="private",
        ),
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=None,
    )
    mortals = MortalMemory({user_id: mortal(id=user_id)})
    subject = ConfigureMortalLocalizationActivity(
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=mortals,
        content=BotContents.debug(),
        keyboards=telegram_keyboards(),
        response_ttl_seconds=3619,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:localization:3617",
        response_key="telegram:localization:3617:response",
        chat_id=user_id,
        user_id=user_id,
        remove_reply_keyboard=True,
    )

    await subject.configure(input)

    response = payloads.responses[input.response_key]
    assert (
        mortals.mortals[user_id].locale,
        response.prelude_text,
        response.text,
        response.remove_reply_keyboard,
    ) == (
        "ru",
        "Язык изменён на русский.",
        "Путь укажут созвездия",
        True,
    ), "reply keyboard locale was not persisted, confirmed, and dismissed"


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
        updates=payloads.update_documents,
        responses=payloads.response_documents,
        mortals=MortalMemory(),
        content=BotContents.debug(),
        keyboards=telegram_keyboards(),
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
