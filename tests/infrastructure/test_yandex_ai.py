from types import SimpleNamespace
from typing import cast

import pytest

from sein_zum_tode.infrastructure.yandex_ai import YandexAIStudioClient
from sein_zum_tode.prediction.config import YandexPredictionConfig
from sein_zum_tode.prediction.models import DeathPrediction

pytestmark = pytest.mark.fast


class ModelDouble:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def configure(self, **options: object) -> ModelDouble:
        self.events.append(("configure", options))
        return self

    async def run(self, messages: object, **options: object) -> object:
        self.events.append(("run", messages, options["timeout"]))
        return SimpleNamespace(
            text='{"days_left": 3701, "message": "Structured"}',
        )


class ModelsDouble:
    def __init__(self, model: ModelDouble) -> None:
        self.model = model
        self.events: list[tuple[object, ...]] = []

    def completions(self, name: str, *, model_version: str) -> ModelDouble:
        self.events.append(("completions", name, model_version))
        return self.model


async def test_enforces_the_adapter_schema_in_yandex_and_returns_a_typed_model() -> None:
    model = ModelDouble()
    models = ModelsDouble(model)
    config = YandexPredictionConfig(
        model="yandexgpt",
        model_version="rc",
        temperature=0.37,
        max_tokens=3719,
        request_timeout_seconds=73,
        enable_server_data_logging=False,
        system_prompt="Return mortality JSON",
    )
    client = YandexAIStudioClient(
        sdk=SimpleNamespace(models=models),
        config=config,
    )

    actual = await client.complete(
        user_prompt="Current date and answers",
        response_format=DeathPrediction,
    )

    configure = cast(dict[str, object], model.events[0][1])
    messages = model.events[1][1]
    assert (
        models.events,
        configure["response_format"],
        messages,
        model.events[1][2],
        actual,
    ) == (
        [("completions", "yandexgpt", "rc")],
        DeathPrediction,
        [
            {"role": "system", "text": "Return mortality JSON"},
            {"role": "user", "text": "Current date and answers"},
        ],
        73,
        DeathPrediction(days_left=3701, message="Structured"),
    ), "infra client did not pass the schema to Yandex structured output"
