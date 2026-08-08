from pathlib import Path

import pytest
from pydantic import ValidationError

from sein_zum_tode.infrastructure.completion_config import (
    CompletionProvider,
    OpenAICompletionConfig,
    YandexCompletionConfig,
)
from sein_zum_tode.prediction.config import (
    DeathPredictionConfig,
    MockPredictionConfig,
    PredictionConfigurationError,
    YamlDeathPredictionConfigLoader,
)

pytestmark = pytest.mark.fast


def test_loads_provider_and_structured_generation_settings(tmp_path: Path) -> None:
    path = tmp_path / "prediction.yaml"
    path.write_text(
        """
provider: yandex
system_prompt: Return structured mortality data
mock:
  days_left: 17
yandex:
  model: yandexgpt
  model_version: rc
  temperature: 0.2
  max_tokens: 777
  request_timeout_seconds: 61
openai:
  model: gpt-5.6-sol
  reasoning_effort: high
  max_output_tokens: 881
  request_timeout_seconds: 67
""".strip(),
        encoding="utf-8",
    )

    actual = YamlDeathPredictionConfigLoader(path).load()

    assert (
        actual.provider,
        actual.mock.days_left,
        actual.yandex.model,
        actual.yandex.max_tokens,
        actual.openai.model,
        actual.openai.reasoning_effort,
        actual.system_prompt,
    ) == (
        CompletionProvider.YANDEX,
        17,
        "yandexgpt",
        777,
        "gpt-5.6-sol",
        "high",
        "Return structured mortality data",
    )


@pytest.mark.parametrize("payload", ["provider: unknown", "provider: ["])
def test_rejects_invalid_prediction_configuration(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(PredictionConfigurationError):
        YamlDeathPredictionConfigLoader(path).load()


def test_rejects_a_missing_prediction_configuration(tmp_path: Path) -> None:
    with pytest.raises(PredictionConfigurationError):
        YamlDeathPredictionConfigLoader(tmp_path / "missing.yaml").load()


def test_rejects_a_fallback_provider_equal_to_the_primary_provider() -> None:
    with pytest.raises(ValidationError, match="fallback_provider must differ"):
        DeathPredictionConfig(
            provider=CompletionProvider.OPENAI,
            fallback_provider=CompletionProvider.OPENAI,
            system_prompt="Return structured data",
            mock=MockPredictionConfig(days_left=17),
            yandex=YandexCompletionConfig(model="yandexgpt", model_version="rc"),
            openai=OpenAICompletionConfig(model="gpt-5.6-sol"),
        )
