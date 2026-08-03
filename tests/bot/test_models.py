import pytest
from pydantic import ValidationError
from temporalio.converter import DataConverter

from sein_zum_tode.bot.models import (
    CleanupPayloadsInput,
    DeliverResponseInput,
    InspectedUpdate,
    InspectionKind,
    PrepareResponseInput,
    TelegramButton,
    TelegramResponse,
)

pytestmark = pytest.mark.fast


def test_derives_the_response_key_from_its_update() -> None:
    inspected = InspectedUpdate(
        kind=InspectionKind.HELP,
        update_key="telegram:quasar:1501",
        chat_id=150_151,
    )

    actual = inspected.response_key()

    assert actual == "telegram:quasar:1501:response", (
        "inspected update derived a response key outside its Redis namespace"
    )


async def test_decodes_historical_activity_payloads_without_observability_fields() -> None:
    converter = DataConverter.default
    payloads = await converter.encode(
        [
            {
                "update_key": "telegram:legacy:1511",
                "response_key": "response:1523",
                "chat_id": 152_329,
            },
            {"response_key": "response:1531"},
            {"keys": ["telegram:legacy:1543", "response:1549"]},
        ]
    )

    actual = await converter.decode(
        payloads,
        [PrepareResponseInput, DeliverResponseInput, CleanupPayloadsInput],
    )

    assert actual == [
        PrepareResponseInput(
            update_key="telegram:legacy:1511",
            response_key="response:1523",
            chat_id=152_329,
            user_id=None,
        ),
        DeliverResponseInput(
            response_key="response:1531",
            update_key=None,
            user_id=None,
        ),
        CleanupPayloadsInput(
            keys=("telegram:legacy:1543", "response:1549"),
            update_key=None,
            user_id=None,
        ),
    ], "new optional Activity fields broke Temporal history deserialization"


def test_rejects_showing_and_removing_a_keyboard_in_one_response() -> None:
    with pytest.raises(ValidationError):
        TelegramResponse(
            chat_id=154_951,
            text="Contradictory keyboard",
            keyboard=(
                (
                    TelegramButton(
                        text="Daily",
                        callback_data="notifications:daily",
                    ),
                ),
            ),
            remove_reply_keyboard=True,
        )
