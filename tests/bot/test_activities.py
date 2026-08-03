from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from aiogram.types import Update
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.activities import (
    CleanupTelegramPayloadsActivity,
    DeliverTelegramResponseActivity,
    InspectTelegramUpdateActivity,
    PrepareTelegramResponseActivities,
)
from sein_zum_tode.bot.content import NotificationTier
from sein_zum_tode.bot.errors import (
    InvalidStoredPayloadError,
    PermanentTelegramDeliveryError,
    TelegramRateLimitedError,
    TelegramRecipientUnavailableError,
)
from sein_zum_tode.bot.models import (
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    InspectUpdateInput,
    PrepareResponseInput,
    TelegramKeyboardMode,
    TelegramResponse,
)
from sein_zum_tode.broadcasts.models import ScreamRequest
from sein_zum_tode.ports.metrics import NoopApplicationMetrics
from tests.support import (
    ActivityCase,
    BotContents,
    MortalMemory,
    SilentLogger,
    TelegramMemory,
    TelegramUpdates,
    mortal,
    telegram_keyboards,
)

pytestmark = pytest.mark.fast
HELP_TEXT = "Navigate by the constellations"
GROUP_UNSUPPORTED_RESPONSE_TEXT = "Group chats are not supported."
SCREAM_DENIED_TEXT = "You can't scream 🤷‍♂️"
PAYLOAD_EXPIRED_RESPONSE_TEXT = "This message expired. Please send it again."


class InspectionMetrics(NoopApplicationMetrics):
    def __init__(self) -> None:
        self.expired: list[str] = []

    def payload_expired(self, *, kind: str) -> None:
        super().payload_expired(kind=kind)
        self.expired.append(kind)


SCREAM_MEDIA: tuple[dict[str, object], ...] = (
    {
        "photo": [
            {
                "file_id": "photo-sphinx-1",
                "file_unique_id": "photo-unique-sphinx-1",
                "width": 317,
                "height": 509,
            }
        ],
        "caption": "Bright vixens",
    },
    {
        "video": {
            "file_id": "video-sphinx-2",
            "file_unique_id": "video-unique-sphinx-2",
            "width": 317,
            "height": 509,
            "duration": 3,
        }
    },
    {
        "animation": {
            "file_id": "animation-sphinx-3",
            "file_unique_id": "animation-unique-sphinx-3",
            "width": 317,
            "height": 509,
            "duration": 5,
        }
    },
    {
        "audio": {
            "file_id": "audio-sphinx-5",
            "file_unique_id": "audio-unique-sphinx-5",
            "duration": 7,
        }
    },
    {
        "document": {
            "file_id": "document-sphinx-7",
            "file_unique_id": "document-unique-sphinx-7",
        }
    },
    {
        "voice": {
            "file_id": "voice-sphinx-11",
            "file_unique_id": "voice-unique-sphinx-11",
            "duration": 13,
        }
    },
    {
        "video_note": {
            "file_id": "note-sphinx-13",
            "file_unique_id": "note-unique-sphinx-13",
            "length": 317,
            "duration": 17,
        }
    },
    {
        "sticker": {
            "file_id": "sticker-sphinx-17",
            "file_unique_id": "sticker-unique-sphinx-17",
            "type": "regular",
            "width": 317,
            "height": 509,
            "is_animated": False,
            "is_video": False,
        }
    },
)


def memory(update: object, response: object = None) -> TelegramMemory:
    return TelegramMemory(
        update_result=update,
        response_result=response,
        store_result=None,
        send_result=None,
        delete_result=None,
    )


@pytest.mark.parametrize(
    "case",
    [
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1259,
                user_id=125_963,
                chat_id=125_969,
                text="Bawds jog, flick quartz",
                chat_type="private",
            ),
            expected_kind=InspectionKind.TEXT,
            expected_chat_id=125_969,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1277,
                user_id=127_781,
                chat_id=127_789,
                text="/help",
                chat_type="private",
            ),
            expected_kind=InspectionKind.HELP,
            expected_chat_id=127_789,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1278,
                user_id=127_881,
                chat_id=127_889,
                text="/about",
                chat_type="private",
            ),
            expected_kind=InspectionKind.ABOUT,
            expected_chat_id=127_889,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1280,
                user_id=128_081,
                chat_id=128_089,
                text="/notifications",
                chat_type="private",
            ),
            expected_kind=InspectionKind.NOTIFICATIONS,
            expected_chat_id=128_089,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1281,
                user_id=128_181,
                chat_id=128_189,
                text="/localization",
                chat_type="private",
            ),
            expected_kind=InspectionKind.LOCALIZATION,
            expected_chat_id=128_189,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1279,
                user_id=127_981,
                chat_id=127_987,
                text="/begin",
                chat_type="private",
            ),
            expected_kind=InspectionKind.BEGIN,
            expected_chat_id=127_987,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1282,
                user_id=128_283,
                chat_id=128_287,
                text="/unknown",
                chat_type="private",
            ),
            expected_kind=InspectionKind.UNSUPPORTED,
            expected_chat_id=128_287,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1284,
                user_id=128_489,
                chat_id=128_491,
                text="/help@mortality_bot",
                chat_type="private",
            ),
            expected_kind=InspectionKind.UNSUPPORTED,
            expected_chat_id=128_491,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1283,
                user_id=128_287,
                chat_id=128_291,
                text=None,
                chat_type="private",
            ),
            expected_kind=InspectionKind.UNSUPPORTED,
            expected_chat_id=128_291,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1291,
                user_id=129_293,
                chat_id=-129_301,
                text="Grumpy wizards",
                chat_type="group",
            ),
            expected_kind=InspectionKind.GROUP_UNSUPPORTED,
            expected_chat_id=-129_301,
        ),
        ActivityCase(
            update=TelegramUpdates.edited(
                update_id=1301,
                user_id=130_303,
                chat_id=130_307,
                text="Edited quartz",
            ),
            expected_kind=InspectionKind.UNSUPPORTED,
            expected_chat_id=130_307,
        ),
        ActivityCase(
            update=TelegramUpdates.callback(
                update_id=1319,
                user_id=131_927,
                chat_id=-131_939,
            ),
            expected_kind=InspectionKind.GROUP_UNSUPPORTED,
            expected_chat_id=-131_939,
            expected_callback_query_id="callback-Sphinx-915",
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1323,
                user_id=132_331,
                chat_id=132_331,
                text="🇷🇺 RU",
                chat_type="private",
            ),
            expected_kind=InspectionKind.LOCALIZATION_SELECTION,
            expected_chat_id=132_331,
            expected_reply_keyboard_selection=True,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1324,
                user_id=132_433,
                chat_id=132_433,
                text="Daily · 09:00",
                chat_type="private",
            ),
            expected_kind=InspectionKind.NOTIFICATION_SELECTION,
            expected_chat_id=132_433,
            expected_reply_keyboard_selection=True,
        ),
        ActivityCase(
            update=TelegramUpdates.message(
                update_id=1325,
                user_id=132_533,
                chat_id=132_533,
                text="✨ Своё расписание",
                chat_type="private",
            ),
            expected_kind=InspectionKind.CUSTOM_NOTIFICATION_SELECTION,
            expected_chat_id=132_533,
            expected_reply_keyboard_selection=True,
        ),
        ActivityCase(
            update=TelegramUpdates.callback(
                update_id=1320,
                user_id=132_021,
                chat_id=132_021,
                chat_type="private",
                data="notifications:weekly",
            ),
            expected_kind=InspectionKind.NOTIFICATION_SELECTION,
            expected_chat_id=132_021,
            expected_callback_query_id="callback-Sphinx-915",
        ),
        ActivityCase(
            update=TelegramUpdates.callback(
                update_id=1321,
                user_id=132_123,
                chat_id=132_123,
                chat_type="private",
                data="notifications:custom",
            ),
            expected_kind=InspectionKind.CUSTOM_NOTIFICATION_SELECTION,
            expected_chat_id=132_123,
            expected_callback_query_id="callback-Sphinx-915",
        ),
        ActivityCase(
            update=TelegramUpdates.callback(
                update_id=1322,
                user_id=132_223,
                chat_id=132_223,
                chat_type="private",
                data="localization:ru",
            ),
            expected_kind=InspectionKind.LOCALIZATION_SELECTION,
            expected_chat_id=132_223,
            expected_callback_query_id="callback-Sphinx-915",
        ),
        ActivityCase(
            update=TelegramUpdates.callback(
                update_id=1326,
                user_id=132_629,
                chat_id=132_629,
                chat_type="private",
                data="unknown:selection",
            ),
            expected_kind=InspectionKind.UNSUPPORTED,
            expected_chat_id=132_629,
            expected_callback_query_id="callback-Sphinx-915",
        ),
        ActivityCase(
            update=TelegramUpdates.membership(
                update_id=1321,
                user_id=132_127,
                bot_id=132_137,
                old_status="member",
                new_status="kicked",
            ),
            expected_kind=InspectionKind.MORTAL_BLOCKED,
            expected_chat_id=132_127,
        ),
        ActivityCase(
            update=TelegramUpdates.membership(
                update_id=1327,
                user_id=132_733,
                bot_id=132_739,
                old_status="member",
                new_status="left",
            ),
            expected_kind=InspectionKind.MORTAL_BLOCKED,
            expected_chat_id=132_733,
        ),
        ActivityCase(
            update=TelegramUpdates.membership(
                update_id=1361,
                user_id=136_163,
                bot_id=136_169,
                old_status="kicked",
                new_status="member",
            ),
            expected_kind=InspectionKind.MORTAL_UNBLOCKED,
            expected_chat_id=136_163,
        ),
        ActivityCase(
            update=TelegramUpdates.membership(
                update_id=1367,
                user_id=136_769,
                bot_id=136_777,
                old_status="member",
                new_status="creator",
            ),
            expected_kind=InspectionKind.UNSUPPORTED,
            expected_chat_id=136_769,
        ),
    ],
)
async def test_classifies_each_supported_update_story(case: ActivityCase) -> None:
    subject = InspectTelegramUpdateActivity(
        memory(case.update).update_documents,
        SilentLogger(),
        keyboards=telegram_keyboards(),
    )

    actual = await subject.inspect(InspectUpdateInput("telegram:cosmos:1321", 132_127))

    assert actual == InspectedUpdate(
        kind=case.expected_kind,
        update_key="telegram:cosmos:1321",
        chat_id=case.expected_chat_id,
        callback_query_id=case.expected_callback_query_id,
        reply_keyboard_selection=case.expected_reply_keyboard_selection,
    ), "inspection selected the wrong response strategy or Telegram chat"


@pytest.mark.parametrize("replied_content", ({"text": "Pack my red box"}, *SCREAM_MEDIA))
async def test_accepts_each_copyable_scream_message(replied_content: dict[str, object]) -> None:
    update = TelegramUpdates.reply_command(
        update_id=1329,
        user_id=162573173,
        text="/scream ru",
        replied_content=replied_content,
    )
    subject = InspectTelegramUpdateActivity(
        update_reader=memory(update).update_documents,
        keyboards=telegram_keyboards(),
        admin_user_ids=frozenset({162573173}),
        logger=SilentLogger(),
    )

    actual = await subject.inspect(
        InspectUpdateInput(update_key="telegram:scream:1329", user_id=162573173)
    )

    assert actual == InspectedUpdate(
        kind=InspectionKind.SCREAM,
        update_key="telegram:scream:1329",
        chat_id=162573173,
        scream_request=ScreamRequest(
            locale="ru",
            source_chat_id=162573173,
            source_message_id=1838,
        ),
    ), "an admin reply lost its target locale or Telegram copy source"


@pytest.mark.parametrize(
    "update",
    [
        TelegramUpdates.reply_command(
            update_id=1363,
            user_id=162573173,
            text="/scream",
            replied_content={"text": "Missing locale"},
        ),
        TelegramUpdates.reply_command(
            update_id=1365,
            user_id=162573173,
            text="/scream de",
            replied_content={"text": "Unknown locale"},
        ),
        TelegramUpdates.reply_command(
            update_id=1369,
            user_id=162573173,
            text="/scream en",
            replied_content=None,
        ),
        TelegramUpdates.reply_command(
            update_id=1371,
            user_id=162573173,
            text="/scream en",
            replied_content={"text": "Album member"},
            media_group_id="album-sphinx-1371",
        ),
        TelegramUpdates.reply_command(
            update_id=1375,
            user_id=162573173,
            text="/scream en",
            replied_content={"location": {"latitude": 47.1, "longitude": 39.7}},
        ),
    ],
)
async def test_rejects_a_malformed_or_unsupported_admin_scream(update: Update) -> None:
    subject = InspectTelegramUpdateActivity(
        update_reader=memory(update).update_documents,
        keyboards=telegram_keyboards(),
        admin_user_ids=frozenset({162573173}),
        logger=SilentLogger(),
    )

    actual = await subject.inspect(
        InspectUpdateInput(update_key="telegram:scream:unsupported", user_id=162573173)
    )

    assert actual.kind == InspectionKind.SCREAM_UNSUPPORTED, (
        "an invalid locale, absent reply, album, or unsupported message started a scream"
    )


async def test_denies_a_non_admin_before_validating_the_scream_shape() -> None:
    update = TelegramUpdates.reply_command(
        update_id=1377,
        user_id=137_779,
        text="/scream unknown",
        replied_content=None,
    )
    subject = InspectTelegramUpdateActivity(
        update_reader=memory(update).update_documents,
        keyboards=telegram_keyboards(),
        admin_user_ids=frozenset({162573173}),
        logger=SilentLogger(),
    )

    actual = await subject.inspect(
        InspectUpdateInput(update_key="telegram:scream:denied", user_id=137_779)
    )

    assert actual.kind == InspectionKind.SCREAM_DENIED, (
        "a non-admin learned scream validation details or bypassed authorization"
    )


@pytest.mark.parametrize("tier", tuple(NotificationTier))
async def test_accepts_each_notification_sample_for_an_admin(
    tier: NotificationTier,
) -> None:
    update = TelegramUpdates.message(
        update_id=1381,
        user_id=162573173,
        chat_id=162573173,
        text=f"/sample {tier.value}",
        chat_type="private",
    )
    subject = InspectTelegramUpdateActivity(
        update_reader=memory(update).update_documents,
        keyboards=telegram_keyboards(),
        admin_user_ids=frozenset({162573173}),
        logger=SilentLogger(),
    )

    actual = await subject.inspect(
        InspectUpdateInput(update_key="telegram:sample:1381", user_id=162573173)
    )

    assert actual == InspectedUpdate(
        kind=InspectionKind.NOTIFICATION_SAMPLE,
        update_key="telegram:sample:1381",
        chat_id=162573173,
        notification_sample=tier,
    ), "an admin notification sample lost its requested reward tier"


@pytest.mark.parametrize(
    ("user_id", "text"),
    [
        (138_307, "/sample lucky"),
        (162573173, "/sample"),
        (162573173, "/sample legendary"),
    ],
)
async def test_hides_invalid_or_non_admin_notification_samples(
    user_id: int,
    text: str,
) -> None:
    update = TelegramUpdates.message(
        update_id=1387,
        user_id=user_id,
        chat_id=user_id,
        text=text,
        chat_type="private",
    )
    subject = InspectTelegramUpdateActivity(
        update_reader=memory(update).update_documents,
        keyboards=telegram_keyboards(),
        admin_user_ids=frozenset({162573173}),
        logger=SilentLogger(),
    )

    actual = await subject.inspect(
        InspectUpdateInput(update_key="telegram:sample:1387", user_id=user_id)
    )

    assert actual.kind == InspectionKind.UNSUPPORTED, (
        "an invalid or non-admin /sample exposed the admin-only command"
    )


@pytest.mark.parametrize(
    "update_outcome",
    [
        InvalidStoredPayloadError("damaged comet 1327"),
        Update.model_validate({"update_id": 1357}),
        TelegramUpdates.anonymous_poll(update_id=1361),
    ],
)
async def test_falls_back_to_the_user_when_update_cannot_be_inspected(
    update_outcome: object,
) -> None:
    subject = InspectTelegramUpdateActivity(
        memory(update_outcome).update_documents,
        SilentLogger(),
        keyboards=telegram_keyboards(),
    )

    actual = await subject.inspect(InspectUpdateInput("telegram:cosmos:1367", 136_777))

    assert actual == InspectedUpdate(
        kind=InspectionKind.UNSUPPORTED,
        update_key="telegram:cosmos:1367",
        chat_id=136_777,
    ), "inspection lost the user fallback for unavailable or unsupported input"


async def test_reports_an_expired_update_without_treating_it_as_user_input() -> None:
    metrics = InspectionMetrics()
    subject = InspectTelegramUpdateActivity(
        update_reader=memory(None).update_documents,
        keyboards=telegram_keyboards(),
        logger=SilentLogger(),
        metrics=metrics,
    )

    actual = await subject.inspect(
        InspectUpdateInput(update_key="telegram:expired:1369", user_id=136_777)
    )

    assert (actual, metrics.expired) == (
        InspectedUpdate(
            kind=InspectionKind.PAYLOAD_EXPIRED,
            update_key="telegram:expired:1369",
            chat_id=136_777,
        ),
        ["telegram_update"],
    ), "an expired Redis payload was hidden as unsupported input or went unmeasured"


@pytest.mark.parametrize(
    ("prepare", "expected_text"),
    [
        (
            lambda subject, input: subject.prepare_help(input),
            HELP_TEXT,
        ),
        (
            lambda subject, input: subject.prepare_group_unsupported(input),
            GROUP_UNSUPPORTED_RESPONSE_TEXT,
        ),
        (
            lambda subject, input: subject.prepare_scream_denied(input),
            SCREAM_DENIED_TEXT,
        ),
        (
            lambda subject, input: subject.prepare_limit_exhausted(input),
            "LLM request limit exhausted",
        ),
        (
            lambda subject, input: subject.prepare_payload_expired(input),
            PAYLOAD_EXPIRED_RESPONSE_TEXT,
        ),
    ],
)
async def test_prepares_each_static_response(
    prepare: Callable[
        [PrepareTelegramResponseActivities, PrepareResponseInput],
        Awaitable[None],
    ],
    expected_text: str,
) -> None:
    payloads = memory(None)
    subject = PrepareTelegramResponseActivities(
        response_store=payloads.response_documents,
        ttl_seconds=1433,
        content=BotContents.debug(),
        mortals=MortalMemory(),
        keyboards=telegram_keyboards(),
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:static:1439",
        response_key="telegram:response:1447",
        chat_id=-144_749,
        user_id=144_751,
    )

    await prepare(subject, input)

    assert payloads.events == [
        (
            "store_response",
            "telegram:response:1447",
            TelegramResponse(chat_id=-144_749, text=expected_text),
            1433,
        )
    ], "static response activity stored an unexpected Telegram message"


async def test_localizes_scream_denial_for_a_russian_mortal() -> None:
    payloads = memory(None)
    subject = PrepareTelegramResponseActivities(
        response_store=payloads.response_documents,
        ttl_seconds=1441,
        content=BotContents.debug(),
        mortals=MortalMemory({144_149: mortal(id=144_149, locale="ru")}),
        keyboards=telegram_keyboards(),
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:scream-denied:1441",
        response_key="telegram:scream-denied:1441:response",
        chat_id=144_149,
        user_id=144_149,
    )

    await subject.prepare_scream_denied(input)

    assert payloads.responses[input.response_key].text == "Ты не можешь кричать 🤷‍♂️", (
        "Russian Mortal received the English admin-only denial"
    )


async def test_prepares_html_about_and_callback_keyboards() -> None:
    payloads = memory(None)
    subject = PrepareTelegramResponseActivities(
        response_store=payloads.response_documents,
        ttl_seconds=1451,
        content=BotContents.debug(),
        mortals=MortalMemory({145_459: mortal(id=145_459)}),
        keyboards=telegram_keyboards(),
        logger=SilentLogger(),
    )
    about = PrepareResponseInput(
        update_key="telegram:about:1453",
        response_key="telegram:about:1453:response",
        chat_id=145_459,
        user_id=145_459,
    )
    notifications = PrepareResponseInput(
        update_key="telegram:notifications:1459",
        response_key="telegram:notifications:1459:response",
        chat_id=145_459,
        user_id=145_459,
    )
    localization = PrepareResponseInput(
        update_key="telegram:localization:1460",
        response_key="telegram:localization:1460:response",
        chat_id=145_459,
        user_id=145_459,
    )
    custom = PrepareResponseInput(
        update_key="telegram:notifications-custom:1461",
        response_key="telegram:notifications-custom:1461:response",
        chat_id=145_459,
        user_id=145_459,
        callback_query_id="callback-Sphinx-915",
    )

    await subject.prepare_about(about)
    await subject.prepare_notifications(notifications)
    await subject.prepare_localization(localization)
    await subject.prepare_custom_notification(custom)

    about_response = payloads.responses[about.response_key]
    notification_response = payloads.responses[notifications.response_key]
    localization_response = payloads.responses[localization.response_key]
    custom_response = payloads.responses[custom.response_key]
    assert (
        about_response.parse_mode,
        "github" in about_response.text,
        tuple(button.callback_data for row in notification_response.keyboard for button in row),
        tuple(button.text for row in notification_response.keyboard for button in row),
        tuple(button.callback_data for row in localization_response.keyboard for button in row),
        notification_response.text,
        custom_response.text,
        custom_response.callback_query_id,
    ) == (
        "HTML",
        True,
        (
            "notifications:daily",
            "notifications:weekly",
            "notifications:monthly",
            "notifications:never",
            "notifications:custom",
        ),
        (
            "Daily · 09:00",
            "Weekly · 09:00",
            "Monthly · 09:00",
            "Never",
            "✨ Custom schedule",
        ),
        (
            "localization:ru",
            "localization:en",
        ),
        "Choose a notification frequency (Europe/Moscow)",
        "Describe a custom notification schedule",
        "callback-Sphinx-915",
    ), "about formatting or callback keyboard changed"


async def test_prepares_reply_keyboards_and_removes_them_before_custom_input() -> None:
    payloads = memory(None)
    content = BotContents.debug()
    subject = PrepareTelegramResponseActivities(
        response_store=payloads.response_documents,
        ttl_seconds=1463,
        content=content,
        mortals=MortalMemory({146_369: mortal(id=146_369)}),
        keyboards=telegram_keyboards(
            content=content,
            mode=TelegramKeyboardMode.REPLY,
        ),
        logger=SilentLogger(),
    )
    localization = PrepareResponseInput(
        update_key="telegram:localization:1463",
        response_key="telegram:localization:1463:response",
        chat_id=146_369,
        user_id=146_369,
    )
    notifications = PrepareResponseInput(
        update_key="telegram:notifications:1463",
        response_key="telegram:notifications:1463:response",
        chat_id=146_369,
        user_id=146_369,
    )
    custom = PrepareResponseInput(
        update_key="telegram:custom:1463",
        response_key="telegram:custom:1463:response",
        chat_id=146_369,
        user_id=146_369,
        remove_reply_keyboard=True,
    )

    await subject.prepare_localization(localization)
    await subject.prepare_notifications(notifications)
    await subject.prepare_custom_notification(custom)

    assert (
        payloads.responses[localization.response_key].keyboard_mode,
        payloads.responses[notifications.response_key].keyboard_mode,
        payloads.responses[custom.response_key].remove_reply_keyboard,
    ) == (
        TelegramKeyboardMode.REPLY,
        TelegramKeyboardMode.REPLY,
        True,
    ), "reply keyboard mode or explicit removal was lost during response preparation"


async def test_rejects_notification_keyboard_for_a_missing_mortal() -> None:
    subject = PrepareTelegramResponseActivities(
        response_store=memory(None).response_documents,
        ttl_seconds=1469,
        content=BotContents.debug(),
        mortals=MortalMemory(),
        keyboards=telegram_keyboards(),
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.prepare_notifications(
            PrepareResponseInput(
                update_key="telegram:notifications:missing-mortal",
                response_key="telegram:notifications:missing-mortal:response",
                chat_id=146_971,
                user_id=146_971,
            )
        )


async def test_delivers_the_response_loaded_from_redis() -> None:
    response = TelegramResponse(chat_id=145_459, text="Sixty zippers were quickly picked")
    payloads = memory(None, response)
    subject = DeliverTelegramResponseActivity(
        response_reader=payloads.response_documents,
        sender=payloads,
        logger=SilentLogger(),
    )

    await subject.deliver(
        DeliverResponseInput(
            response_key="telegram:response:1459",
            update_key="telegram:update:1451",
            user_id=145_463,
        )
    )

    assert payloads.events == [
        ("load_response", "telegram:response:1459"),
        ("send_text", 145_459, "Sixty zippers were quickly picked"),
    ], "delivery changed the stored response before sending it"


@pytest.mark.parametrize(
    "response_outcome",
    [None, InvalidStoredPayloadError("response shards 1471")],
)
async def test_rejects_an_unavailable_delivery_payload(response_outcome: object) -> None:
    payloads = memory(None, response_outcome)
    subject = DeliverTelegramResponseActivity(
        response_reader=payloads.response_documents,
        sender=payloads,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.deliver(
            DeliverResponseInput(
                response_key="telegram:response:1481",
                update_key=None,
                user_id=None,
            )
        )


async def test_rejects_a_permanent_telegram_delivery_failure() -> None:
    response = TelegramResponse(chat_id=148_741, text="Jackdaws love my big sphinx")
    payloads = TelegramMemory(
        update_result=None,
        response_result=response,
        store_result=None,
        send_result=PermanentTelegramDeliveryError("chat forbidden 1487"),
        delete_result=None,
    )
    subject = DeliverTelegramResponseActivity(
        response_reader=payloads.response_documents,
        sender=payloads,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError):
        await subject.deliver(
            DeliverResponseInput(
                response_key="telegram:response:1489",
                update_key=None,
                user_id=None,
            )
        )


async def test_retries_a_rate_limited_delivery_after_telegram_delay() -> None:
    response = TelegramResponse(chat_id=148_743, text="Wait for the next orbit")
    payloads = TelegramMemory(
        update_result=None,
        response_result=response,
        store_result=None,
        send_result=TelegramRateLimitedError(retry_after_seconds=31),
        delete_result=None,
    )
    subject = DeliverTelegramResponseActivity(
        response_reader=payloads.response_documents,
        sender=payloads,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError) as captured:
        await subject.deliver(
            DeliverResponseInput(
                response_key="telegram:response:rate-limit:1491",
                user_id=148_743,
            )
        )

    assert (
        captured.value.type,
        captured.value.next_retry_delay,
        captured.value.non_retryable,
    ) == (
        "TelegramRateLimited",
        timedelta(seconds=31),
        False,
    ), "delivery Activity ignored Telegram retry-after semantics"


async def test_marks_a_forbidden_recipient_for_mortal_deactivation() -> None:
    response = TelegramResponse(chat_id=149_501, text="Sphinx of black quartz")
    payloads = TelegramMemory(
        update_result=None,
        response_result=response,
        store_result=None,
        send_result=TelegramRecipientUnavailableError("recipient unavailable 1499"),
        delete_result=None,
    )
    subject = DeliverTelegramResponseActivity(
        response_reader=payloads.response_documents,
        sender=payloads,
        logger=SilentLogger(),
    )

    with pytest.raises(ApplicationError) as raised:
        await subject.deliver(
            DeliverResponseInput(
                response_key="telegram:response:1511",
                update_key=None,
                user_id=149_501,
            )
        )

    assert raised.value.type == "TelegramRecipientUnavailable", (
        "forbidden delivery did not expose the workflow lifecycle error type"
    )


async def test_cleans_both_ephemeral_payloads() -> None:
    payloads = memory(None)
    subject = CleanupTelegramPayloadsActivity(payloads, SilentLogger())
    keys = ("telegram:update:1493", "telegram:response:1499")

    await subject.cleanup(
        CleanupPayloadsInput(
            keys=keys,
            update_key="telegram:update:1493",
            user_id=149_501,
        )
    )

    assert payloads.events == [("delete", keys)], (
        "cleanup failed to delete both the update and response references"
    )


async def test_propagates_an_ephemeral_payload_cleanup_failure() -> None:
    failure = RuntimeError("redis cleanup failed 1523")
    payloads = TelegramMemory(
        update_result=None,
        response_result=None,
        store_result=None,
        send_result=None,
        delete_result=failure,
    )
    subject = CleanupTelegramPayloadsActivity(
        cleaner=payloads,
        logger=SilentLogger(),
    )

    with pytest.raises(RuntimeError) as raised:
        await subject.cleanup(
            CleanupPayloadsInput(
                keys=("telegram:update:1517",),
                update_key="telegram:update:1517",
                user_id=151_701,
            )
        )

    assert raised.value is failure, "cleanup swallowed the failure required for Activity retry"
