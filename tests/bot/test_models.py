from temporalio.converter import DataConverter

from sein_zum_tode.bot.models import (
    CleanupPayloadsInput,
    DeliverResponseInput,
    PrepareResponseInput,
)


async def test_historical_activity_inputs_default_observability_fields() -> None:
    payloads = await DataConverter.default.encode(
        [
            {
                "update_key": "update-key",
                "response_key": "response-key",
                "chat_id": 30,
            },
            {"response_key": "response-key"},
            {"keys": ["update-key", "response-key"]},
        ]
    )
    prepare, deliver, cleanup = await DataConverter.default.decode(
        payloads,
        [
            PrepareResponseInput,
            DeliverResponseInput,
            CleanupPayloadsInput,
        ],
    )

    assert prepare.user_id is None
    assert deliver.user_id is None
    assert deliver.update_key is None
    assert cleanup.user_id is None
    assert cleanup.update_key is None
