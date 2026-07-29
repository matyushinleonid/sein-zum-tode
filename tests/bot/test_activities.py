from collections.abc import Awaitable, Callable

import pytest
from aiogram.types import Update
from temporalio.exceptions import ApplicationError

from sein_zum_tode.bot.activities import (
    CleanupTelegramPayloadsActivity,
    DeliverTelegramResponseActivity,
    InspectTelegramUpdateActivity,
    PrepareTelegramResponseActivities,
)
from sein_zum_tode.bot.errors import (
    InvalidStoredPayloadError,
    PermanentTelegramDeliveryError,
)
from sein_zum_tode.bot.models import (
    GROUP_UNSUPPORTED_RESPONSE_TEXT,
    HELP_RESPONSE_TEXT,
    UNSUPPORTED_RESPONSE_TEXT,
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    InspectUpdateInput,
    PrepareResponseInput,
    TelegramResponse,
)
from tests.support import ActivityCase, SilentLogger, TelegramMemory, TelegramUpdates

pytestmark = pytest.mark.fast


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
            expected_kind=InspectionKind.ECHO,
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
        ),
    ],
)
async def test_classifies_each_supported_update_story(case: ActivityCase) -> None:
    subject = InspectTelegramUpdateActivity(memory(case.update), SilentLogger())

    actual = await subject.inspect(InspectUpdateInput("telegram:cosmos:1321", 132_127))

    assert actual == InspectedUpdate(
        kind=case.expected_kind,
        update_key="telegram:cosmos:1321",
        chat_id=case.expected_chat_id,
    ), "inspection selected the wrong response strategy or Telegram chat"


@pytest.mark.parametrize(
    "update_outcome",
    [
        None,
        InvalidStoredPayloadError("damaged comet 1327"),
        Update.model_validate({"update_id": 1357}),
        TelegramUpdates.anonymous_poll(update_id=1361),
    ],
)
async def test_falls_back_to_the_user_when_update_cannot_be_inspected(
    update_outcome: object,
) -> None:
    subject = InspectTelegramUpdateActivity(memory(update_outcome), SilentLogger())

    actual = await subject.inspect(InspectUpdateInput("telegram:cosmos:1367", 136_777))

    assert actual == InspectedUpdate(
        kind=InspectionKind.UNSUPPORTED,
        update_key="telegram:cosmos:1367",
        chat_id=136_777,
    ), "inspection lost the user fallback for unavailable or unsupported input"


@pytest.mark.parametrize(
    ("update_outcome", "expected_text"),
    [
        (
            TelegramUpdates.message(
                update_id=1373,
                user_id=137_377,
                chat_id=137_383,
                text="Sympathizing would fix Quaker objectives",
                chat_type="private",
            ),
            "Sympathizing would fix Quaker objectives",
        ),
        (None, UNSUPPORTED_RESPONSE_TEXT),
        (
            TelegramUpdates.message(
                update_id=1381,
                user_id=138_191,
                chat_id=138_197,
                text=None,
                chat_type="private",
            ),
            UNSUPPORTED_RESPONSE_TEXT,
        ),
        (InvalidStoredPayloadError("fractured payload 1399"), UNSUPPORTED_RESPONSE_TEXT),
    ],
)
async def test_prepares_echo_or_safe_fallback(
    update_outcome: object,
    expected_text: str,
) -> None:
    payloads = memory(update_outcome)
    subject = PrepareTelegramResponseActivities(
        update_reader=payloads,
        response_store=payloads,
        ttl_seconds=1409,
        logger=SilentLogger(),
    )
    input = PrepareResponseInput(
        update_key="telegram:echo:1423",
        response_key="telegram:response:1427",
        chat_id=142_751,
        user_id=142_757,
    )

    await subject.prepare_echo(input)

    assert payloads.events == [
        ("load_update", "telegram:echo:1423"),
        (
            "store_response",
            "telegram:response:1427",
            TelegramResponse(chat_id=142_751, text=expected_text),
            1409,
        ),
    ], "echo preparation stored the wrong response or Redis TTL"


@pytest.mark.parametrize(
    ("prepare", "expected_text"),
    [
        (
            lambda subject, input: subject.prepare_help(input),
            HELP_RESPONSE_TEXT,
        ),
        (
            lambda subject, input: subject.prepare_unsupported(input),
            UNSUPPORTED_RESPONSE_TEXT,
        ),
        (
            lambda subject, input: subject.prepare_group_unsupported(input),
            GROUP_UNSUPPORTED_RESPONSE_TEXT,
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
        update_reader=payloads,
        response_store=payloads,
        ttl_seconds=1433,
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


async def test_delivers_the_response_loaded_from_redis() -> None:
    response = TelegramResponse(chat_id=145_459, text="Sixty zippers were quickly picked")
    payloads = memory(None, response)
    subject = DeliverTelegramResponseActivity(
        response_reader=payloads,
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
        response_reader=payloads,
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
        response_reader=payloads,
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
