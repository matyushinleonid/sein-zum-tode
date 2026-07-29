import logging
from unittest.mock import Mock, create_autospec

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
    InspectionKind,
    InspectUpdateInput,
    PrepareResponseInput,
    TelegramResponse,
)
from sein_zum_tode.bot.ports import (
    TelegramMessageSender,
    TelegramPayloadCleaner,
    TelegramResponseReader,
    TelegramResponseStore,
    TelegramUpdateReader,
)


def message_update(
    *,
    text: str | None = "hello",
    chat_id: int = 30,
    chat_type: str = "private",
) -> Update:
    message: dict[str, object] = {
        "message_id": 10,
        "date": 1_700_000_000,
        "chat": {"id": chat_id, "type": chat_type},
        "from": {
            "id": 40,
            "is_bot": False,
            "first_name": "Ada",
        },
    }
    if text is not None:
        message["text"] = text
    else:
        message["sticker"] = {
            "file_id": "file",
            "file_unique_id": "unique",
            "type": "regular",
            "width": 10,
            "height": 10,
            "is_animated": False,
            "is_video": False,
        }
    return Update.model_validate({"update_id": 1, "message": message})


def edited_message_update() -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "edited_message": {
                "message_id": 10,
                "date": 1_700_000_000,
                "edit_date": 1_700_000_001,
                "chat": {"id": 30, "type": "private"},
                "from": {
                    "id": 40,
                    "is_bot": False,
                    "first_name": "Ada",
                },
                "text": "edited",
            },
        }
    )


def callback_update() -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "callback_query": {
                "id": "callback",
                "from": {
                    "id": 40,
                    "is_bot": False,
                    "first_name": "Ada",
                },
                "chat_instance": "instance",
                "message": {
                    "message_id": 10,
                    "date": 1_700_000_000,
                    "chat": {"id": -30, "type": "group", "title": "Group"},
                },
            },
        }
    )


@pytest.mark.parametrize(
    ("update", "kind", "chat_id"),
    [
        (message_update(text="hello"), InspectionKind.ECHO, 30),
        (message_update(text="/help"), InspectionKind.HELP, 30),
        (message_update(text=None), InspectionKind.UNSUPPORTED, 30),
        (
            message_update(text="hello", chat_id=-30, chat_type="group"),
            InspectionKind.GROUP_UNSUPPORTED,
            -30,
        ),
        (edited_message_update(), InspectionKind.UNSUPPORTED, 30),
        (callback_update(), InspectionKind.GROUP_UNSUPPORTED, -30),
    ],
)
async def test_inspect_classifies_update(
    update: Update,
    kind: InspectionKind,
    chat_id: int,
) -> None:
    reader = create_autospec(TelegramUpdateReader, instance=True)
    reader.load_update.return_value = update
    inspect = InspectTelegramUpdateActivity(reader)

    result = await inspect.inspect(InspectUpdateInput("update-key", user_id=40))

    assert result.kind == kind
    assert result.update_key == "update-key"
    assert result.chat_id == chat_id
    assert result.response_key() == "update-key:response"


@pytest.mark.parametrize(
    "loaded",
    [
        None,
        InvalidStoredPayloadError("invalid"),
    ],
)
async def test_inspect_falls_back_to_user_for_unavailable_payload(
    loaded: object,
) -> None:
    reader = create_autospec(TelegramUpdateReader, instance=True)
    if isinstance(loaded, Exception):
        reader.load_update.side_effect = loaded
    else:
        reader.load_update.return_value = loaded
    inspect = InspectTelegramUpdateActivity(reader)

    result = await inspect.inspect(InspectUpdateInput("update-key", user_id=40))

    assert result.kind == InspectionKind.UNSUPPORTED
    assert result.chat_id == 40


async def test_inspect_handles_unknown_update_type() -> None:
    reader = create_autospec(TelegramUpdateReader, instance=True)
    reader.load_update.return_value = Update(update_id=1)
    inspect = InspectTelegramUpdateActivity(reader)

    result = await inspect.inspect(InspectUpdateInput("update-key", user_id=40))

    assert result.kind == InspectionKind.UNSUPPORTED
    assert result.chat_id == 40


def prepare_activities(
    update_reader: TelegramUpdateReader,
    response_store: TelegramResponseStore,
) -> PrepareTelegramResponseActivities:
    return PrepareTelegramResponseActivities(
        update_reader=update_reader,
        response_store=response_store,
        ttl_seconds=600,
    )


def prepare_input() -> PrepareResponseInput:
    return PrepareResponseInput(
        update_key="update-key",
        response_key="response-key",
        chat_id=30,
        user_id=40,
    )


async def test_prepare_echo_stores_original_text() -> None:
    reader = create_autospec(TelegramUpdateReader, instance=True)
    store = create_autospec(TelegramResponseStore, instance=True)
    reader.load_update.return_value = message_update(text="sensitive")
    prepare = prepare_activities(reader, store)

    await prepare.prepare_echo(prepare_input())

    store.store_response.assert_awaited_once_with(
        "response-key",
        TelegramResponse(chat_id=30, text="sensitive"),
        600,
    )


@pytest.mark.parametrize(
    "loaded",
    [
        None,
        message_update(text=None),
        InvalidStoredPayloadError("invalid"),
    ],
)
async def test_prepare_echo_stores_unsupported_when_text_is_unavailable(
    loaded: object,
) -> None:
    reader = create_autospec(TelegramUpdateReader, instance=True)
    store = create_autospec(TelegramResponseStore, instance=True)
    if isinstance(loaded, Exception):
        reader.load_update.side_effect = loaded
    else:
        reader.load_update.return_value = loaded
    prepare = prepare_activities(reader, store)

    await prepare.prepare_echo(prepare_input())

    store.store_response.assert_awaited_once_with(
        "response-key",
        TelegramResponse(chat_id=30, text=UNSUPPORTED_RESPONSE_TEXT),
        600,
    )


@pytest.mark.parametrize(
    ("method_name", "text"),
    [
        ("prepare_help", HELP_RESPONSE_TEXT),
        ("prepare_unsupported", UNSUPPORTED_RESPONSE_TEXT),
        ("prepare_group_unsupported", GROUP_UNSUPPORTED_RESPONSE_TEXT),
    ],
)
async def test_prepare_static_response(method_name: str, text: str) -> None:
    reader = create_autospec(TelegramUpdateReader, instance=True)
    store = create_autospec(TelegramResponseStore, instance=True)
    prepare = prepare_activities(reader, store)

    await getattr(prepare, method_name)(prepare_input())

    store.store_response.assert_awaited_once_with(
        "response-key",
        TelegramResponse(chat_id=30, text=text),
        600,
    )


async def test_delivery_sends_stored_response() -> None:
    reader = create_autospec(TelegramResponseReader, instance=True)
    sender = create_autospec(TelegramMessageSender, instance=True)
    reader.load_response.return_value = TelegramResponse(chat_id=30, text="ready")
    deliver = DeliverTelegramResponseActivity(reader, sender)

    await deliver.deliver(DeliverResponseInput("response-key"))

    sender.send_text.assert_awaited_once_with(30, "ready")


async def test_delivery_rejects_invalid_stored_response() -> None:
    reader = create_autospec(TelegramResponseReader, instance=True)
    sender = create_autospec(TelegramMessageSender, instance=True)
    reader.load_response.side_effect = InvalidStoredPayloadError("invalid")
    deliver = DeliverTelegramResponseActivity(reader, sender)

    with pytest.raises(ApplicationError) as raised:
        await deliver.deliver(DeliverResponseInput("response-key"))

    assert raised.value.type == "InvalidTelegramResponse"
    assert raised.value.non_retryable


async def test_delivery_rejects_missing_stored_response() -> None:
    reader = create_autospec(TelegramResponseReader, instance=True)
    sender = create_autospec(TelegramMessageSender, instance=True)
    reader.load_response.return_value = None
    deliver = DeliverTelegramResponseActivity(reader, sender)

    with pytest.raises(ApplicationError) as raised:
        await deliver.deliver(DeliverResponseInput("response-key"))

    assert raised.value.type == "TelegramResponseNotFound"
    assert raised.value.non_retryable


async def test_delivery_marks_permanent_telegram_error_non_retryable() -> None:
    reader = create_autospec(TelegramResponseReader, instance=True)
    sender = create_autospec(TelegramMessageSender, instance=True)
    reader.load_response.return_value = TelegramResponse(chat_id=30, text="ready")
    sender.send_text.side_effect = PermanentTelegramDeliveryError("rejected")
    deliver = DeliverTelegramResponseActivity(reader, sender)

    with pytest.raises(ApplicationError) as raised:
        await deliver.deliver(DeliverResponseInput("response-key"))

    assert raised.value.type == "PermanentTelegramDeliveryError"
    assert raised.value.non_retryable


async def test_cleanup_deletes_all_payloads() -> None:
    cleaner = create_autospec(TelegramPayloadCleaner, instance=True)
    cleanup = CleanupTelegramPayloadsActivity(cleaner)

    await cleanup.cleanup(CleanupPayloadsInput(("update-key", "response-key")))

    cleaner.delete.assert_awaited_once_with(("update-key", "response-key"))


async def test_pipeline_logs_metadata_without_sensitive_payload() -> None:
    secret = "sensitive-message-body"
    update_reader = create_autospec(TelegramUpdateReader, instance=True)
    response_store = create_autospec(TelegramResponseStore, instance=True)
    response_reader = create_autospec(TelegramResponseReader, instance=True)
    sender = create_autospec(TelegramMessageSender, instance=True)
    cleaner = create_autospec(TelegramPayloadCleaner, instance=True)
    logger = Mock(spec=logging.Logger)
    update_reader.load_update.return_value = message_update(text=secret)
    response_reader.load_response.return_value = TelegramResponse(chat_id=30, text=secret)
    inspect = InspectTelegramUpdateActivity(update_reader, logger)
    prepare = PrepareTelegramResponseActivities(
        update_reader,
        response_store,
        ttl_seconds=600,
        logger=logger,
    )
    deliver = DeliverTelegramResponseActivity(
        response_reader,
        sender,
        logger,
    )
    cleanup = CleanupTelegramPayloadsActivity(cleaner, logger)

    await inspect.inspect(InspectUpdateInput("update-key", user_id=40))
    await prepare.prepare_echo(prepare_input())
    await deliver.deliver(
        DeliverResponseInput(
            "update-key:response",
            update_key="update-key",
            user_id=40,
        )
    )
    await cleanup.cleanup(
        CleanupPayloadsInput(
            ("update-key", "response-key"),
            update_key="update-key",
            user_id=40,
        )
    )

    assert [call.args[0] for call in logger.info.call_args_list] == [
        "Telegram update inspected",
        "Telegram response prepared",
        "Telegram response delivered",
    ]
    for call in (*logger.info.call_args_list, *logger.debug.call_args_list):
        fields = call.kwargs["extra"]
        assert fields["user_id"] == 40
        assert fields["update_key"] == "update-key"
        assert isinstance(fields["duration_ms"], float)
        assert secret not in str(call)
