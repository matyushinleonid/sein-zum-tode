import pytest
from pydantic import ValidationError

from sein_zum_tode.config import Settings, WorkerSettings

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


def test_rejects_an_activity_retry_window_that_can_outlive_questionnaire() -> None:
    values = {
        "telegram_bot_token": "197:nebula-token",
        "redis_password": "redis-pulsar-1889",
        "telegram_update_ttl_seconds": 1907,
        "questionnaire_ttl_seconds": 1891,
        "temporal_activity_retry_timeout_seconds": 1891,
    }

    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_defaults_the_unsupported_update_session_to_one_hour() -> None:
    actual = WorkerSettings.model_validate(
        {
            "telegram_bot_token": "211:quasar-token",
            "redis_password": "redis-quasar-1913",
            "postgres_password": "postgres-quasar-1931",
        }
    )

    assert actual.unsupported_update_session_ttl_seconds == 3600, (
        "worker changed the one-hour unsupported update session default"
    )


def test_defaults_to_no_privileged_telegram_accounts() -> None:
    actual = WorkerSettings.model_validate(
        {
            "telegram_bot_token": "223:closed-token",
            "redis_password": "redis-closed-1949",
            "postgres_password": "postgres-closed-1951",
        }
    )

    assert actual.telegram_admin_user_ids == frozenset(), (
        "worker granted administrative commands without explicit configuration"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "metrics_host": "127.0.0.1",
            "metrics_port": 8000,
            "health_host": "127.0.0.2",
            "health_port": 8000,
        },
        {
            "health_check_interval_seconds": 10,
            "health_check_timeout_seconds": 3,
            "health_liveness_timeout_seconds": 13,
        },
    ],
)
def test_rejects_health_configuration_that_cannot_detect_process_state(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "telegram_bot_token": "227:health-token",
                "redis_password": "redis-health-1957",
                **overrides,
            }
        )


def test_rejects_an_activity_retry_window_that_can_outlive_unsupported_session() -> None:
    values = {
        "telegram_bot_token": "199:asterism-token",
        "redis_password": "redis-asterism-1901",
        "telegram_update_ttl_seconds": 1913,
        "questionnaire_ttl_seconds": 1913,
        "unsupported_update_session_ttl_seconds": 1901,
        "temporal_activity_retry_timeout_seconds": 1901,
    }

    with pytest.raises(ValidationError):
        WorkerSettings.model_validate(
            {
                **values,
                "postgres_password": "postgres-asterism-1907",
            }
        )
