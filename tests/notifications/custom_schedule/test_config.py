from pathlib import Path

import pytest

from sein_zum_tode.infrastructure.completion_config import CompletionProvider
from sein_zum_tode.notifications.custom_schedule.config import (
    NotificationPresets,
    NotificationScheduleConfigurationError,
    YamlNotificationScheduleConfigLoader,
)
from sein_zum_tode.notifications.custom_schedule.models import (
    CronOperation,
    TimezoneOperation,
)

pytestmark = pytest.mark.fast


def test_loads_structured_schedule_interpreter_configuration(tmp_path: Path) -> None:
    path = tmp_path / "notification-schedule.yaml"
    path.write_text(
        """
default_timezone: Asia/Tokyo
default_frequency: weekly
presets:
  daily: "17 8 * * *"
  weekly: "19 9 * * 2"
  monthly: "23 10 3 * *"
  never: null
provider: yandex
minimum_interval_hours: 19
system_prompt: Return a structured cron proposal
mock:
  cron_operation: set
  cron_expression: "0 12 * * *"
  timezone_operation: keep
  timezone: null
yandex:
  model: aliceai-llm
  model_version: latest
  temperature: 0.2
  max_tokens: 701
  request_timeout_seconds: 181
openai:
  model: gpt-5.6-sol
  reasoning_effort: high
  max_output_tokens: 709
  request_timeout_seconds: 191
""".strip(),
        encoding="utf-8",
    )

    actual = YamlNotificationScheduleConfigLoader(path).load()

    assert (
        actual.provider,
        actual.default_timezone,
        actual.default_cron(),
        actual.minimum_interval_hours,
        actual.mock.cron_operation,
        actual.mock.timezone_operation,
        actual.yandex.max_tokens,
        actual.openai.reasoning_effort,
    ) == (
        CompletionProvider.YANDEX,
        "Asia/Tokyo",
        "19 9 * * 2",
        19,
        CronOperation.SET,
        TimezoneOperation.KEEP,
        701,
        "high",
    )


def test_maps_every_notification_preset_to_its_configured_cron() -> None:
    from sein_zum_tode.notifications.models import NotificationFrequency

    presets = NotificationPresets(
        daily="17 8 * * *",
        weekly="19 9 * * 2",
        monthly="23 10 3 * *",
        never=None,
    )

    assert tuple(presets.cron(frequency) for frequency in NotificationFrequency) == (
        "17 8 * * *",
        "19 9 * * 2",
        "23 10 3 * *",
        None,
    )


@pytest.mark.parametrize(
    "payload",
    [
        "provider: [",
        "provider: unknown",
        """
provider: mock
minimum_interval_hours: 20
system_prompt: Prompt
mock:
  cron_operation: keep
  timezone_operation: keep
yandex: {model: a, model_version: latest}
openai: {model: b}
""",
        """
provider: mock
system_prompt: Prompt
mock:
  cron_operation: set
  timezone_operation: keep
yandex: {model: a, model_version: latest}
openai: {model: b}
""",
        """
provider: mock
system_prompt: Prompt
mock:
  cron_operation: disable
  timezone_operation: set
yandex: {model: a, model_version: latest}
openai: {model: b}
""",
    ],
)
def test_rejects_invalid_schedule_interpreter_configuration(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "invalid-notification-schedule.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(NotificationScheduleConfigurationError):
        YamlNotificationScheduleConfigLoader(path).load()


def test_rejects_a_missing_schedule_interpreter_configuration(tmp_path: Path) -> None:
    with pytest.raises(NotificationScheduleConfigurationError):
        YamlNotificationScheduleConfigLoader(tmp_path / "missing.yaml").load()


@pytest.mark.parametrize(
    ("timezone", "daily"),
    [
        ("Mars/Olympus_Mons", "17 8 * * *"),
        ("Europe/Moscow", "invalid"),
        ("Europe/Moscow", "*/5 * * * *"),
    ],
)
def test_rejects_invalid_or_too_frequent_configured_presets(
    tmp_path: Path,
    timezone: str,
    daily: str,
) -> None:
    path = tmp_path / "invalid-presets.yaml"
    path.write_text(
        f"""
default_timezone: {timezone}
default_frequency: daily
presets:
  daily: "{daily}"
  weekly: "19 9 * * 2"
  monthly: "23 10 3 * *"
  never: null
provider: mock
minimum_interval_hours: 20
system_prompt: Prompt
mock:
  cron_operation: set
  cron_expression: "0 12 * * *"
  timezone_operation: keep
  timezone: null
yandex: {{model: a, model_version: latest}}
openai: {{model: b}}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(NotificationScheduleConfigurationError):
        YamlNotificationScheduleConfigLoader(path).load()
