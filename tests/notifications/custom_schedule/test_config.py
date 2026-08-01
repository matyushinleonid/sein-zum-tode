from pathlib import Path

import pytest

from sein_zum_tode.infrastructure.completion_config import CompletionProvider
from sein_zum_tode.notifications.custom_schedule.config import (
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
        actual.minimum_interval_hours,
        actual.mock.cron_operation,
        actual.mock.timezone_operation,
        actual.yandex.max_tokens,
        actual.openai.reasoning_effort,
    ) == (
        CompletionProvider.YANDEX,
        19,
        CronOperation.SET,
        TimezoneOperation.KEEP,
        701,
        "high",
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
