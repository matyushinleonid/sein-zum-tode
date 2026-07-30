from pathlib import Path

import pytest

from sein_zum_tode.prediction.config import (
    PredictionConfigurationError,
    PredictionProvider,
    YamlDeathPredictionConfigLoader,
)

pytestmark = pytest.mark.fast


def test_loads_provider_and_structured_generation_settings(tmp_path: Path) -> None:
    path = tmp_path / "prediction.yaml"
    path.write_text(
        """
provider: yandex
mock:
  days_left: 17
yandex:
  model: yandexgpt
  model_version: rc
  temperature: 0.2
  max_tokens: 777
  request_timeout_seconds: 61
  enable_server_data_logging: false
  system_prompt: Return structured mortality data
""".strip(),
        encoding="utf-8",
    )

    actual = YamlDeathPredictionConfigLoader(path).load()

    assert (
        actual.provider,
        actual.mock.days_left,
        actual.yandex.model,
        actual.yandex.max_tokens,
        actual.yandex.enable_server_data_logging,
    ) == (
        PredictionProvider.YANDEX,
        17,
        "yandexgpt",
        777,
        False,
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
