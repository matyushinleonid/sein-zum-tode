import pytest
from pydantic import ValidationError

from sein_zum_tode.config import Settings

pytestmark = pytest.mark.fast


def test_rejects_an_activity_retry_window_that_can_outlive_redis_payload() -> None:
    values = {
        "telegram_bot_token": "191:quasar-token",
        "redis_password": "redis-nebula-1873",
        "telegram_update_ttl_seconds": 1877,
        "temporal_activity_retry_timeout_seconds": 1877,
    }

    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_accepts_an_activity_retry_window_shorter_than_redis_payload() -> None:
    values = {
        "telegram_bot_token": "193:pulsar-token",
        "redis_password": "redis-aurora-1879",
        "telegram_update_ttl_seconds": 1889,
        "temporal_activity_retry_timeout_seconds": 1883,
    }

    actual = Settings.model_validate(values)

    assert actual.temporal_activity_retry_timeout_seconds == 1883, (
        "settings rejected an Activity retry window contained within Redis TTL"
    )


def test_rejects_an_activity_retry_window_that_can_outlive_conversation() -> None:
    values = {
        "telegram_bot_token": "197:nebula-token",
        "redis_password": "redis-pulsar-1889",
        "telegram_update_ttl_seconds": 1907,
        "conversation_ttl_seconds": 1891,
        "temporal_activity_retry_timeout_seconds": 1891,
    }

    with pytest.raises(ValidationError):
        Settings.model_validate(values)
