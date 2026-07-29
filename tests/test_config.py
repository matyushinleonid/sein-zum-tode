import pytest
from pydantic import ValidationError

from sein_zum_tode.config import Settings


def make_settings(**overrides: object) -> Settings:
    values = {
        "telegram_bot_token": "42:token",
        "redis_password": "redis-secret",
        "telegram_update_ttl_seconds": 600,
        "temporal_activity_retry_timeout_seconds": 300,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_activity_retry_timeout_must_be_less_than_payload_ttl() -> None:
    with pytest.raises(
        ValidationError,
        match="TEMPORAL_ACTIVITY_RETRY_TIMEOUT_SECONDS must be less than",
    ):
        make_settings(
            telegram_update_ttl_seconds=300,
            temporal_activity_retry_timeout_seconds=300,
        )


def test_activity_retry_timeout_accepts_shorter_duration() -> None:
    settings = make_settings(
        telegram_update_ttl_seconds=301,
        temporal_activity_retry_timeout_seconds=300,
    )

    assert settings.temporal_activity_retry_timeout_seconds == 300
