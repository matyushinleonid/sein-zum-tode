from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from pydantic import BaseModel
from yandex_ai_studio_sdk import AsyncAIStudio

from sein_zum_tode.infrastructure.yandex_ai import (
    YandexAIStudioClient,
    YandexCompletionProfile,
    YandexTextMessage,
    classify_yandex_error,
)
from sein_zum_tode.ports.completion import CompletionErrorKind, CompletionFailure

pytestmark = pytest.mark.fast


class CompletionResult(BaseModel):
    value: int
    explanation: str


class ModelDouble:
    def __init__(self, text: str = '{"value": 3701, "explanation": "Structured"}') -> None:
        self._text = text
        self.events: list[tuple[object, ...]] = []

    def configure(self, **options: object) -> ModelDouble:
        self.events.append(("configure", options))
        return self

    async def run(self, messages: object, **options: object) -> object:
        self.events.append(("run", messages, options["timeout"]))
        return SimpleNamespace(text=self._text)


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
    profile = YandexCompletionProfile(
        model="yandexgpt",
        model_version="rc",
        temperature=0.37,
        max_tokens=3719,
        request_timeout_seconds=73,
        system_prompt="Return mortality JSON",
    )
    sdk = Mock(spec=AsyncAIStudio)
    sdk.models = models
    client = YandexAIStudioClient(
        sdk=sdk,
        profile=profile,
        response_type=CompletionResult,
    )

    actual = await client.complete(user_prompt="Current date and answers")
    await client.close()

    configure = cast(dict[str, object], model.events[0][1])
    messages = model.events[1][1]
    assert (
        models.events,
        configure["response_format"],
        messages,
        model.events[1][2],
        client.provider_name,
        client.consumes_quota,
        actual,
    ) == (
        [("completions", "yandexgpt", "rc")],
        CompletionResult,
        [
            YandexTextMessage(role="system", text="Return mortality JSON"),
            YandexTextMessage(role="user", text="Current date and answers"),
        ],
        73,
        "yandex",
        True,
        CompletionResult(value=3701, explanation="Structured"),
    ), "infra client did not pass the schema to Yandex structured output"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("slow"), "timeout"),
        (ValueError("nonsense"), "unknown"),
    ],
)
def test_classifies_yandex_failures_into_a_bounded_error_kind(
    error: Exception,
    expected: str,
) -> None:
    assert classify_yandex_error(error).value == expected, (
        "a Yandex failure was classified into the wrong bounded error kind"
    )


async def test_reports_unparseable_yandex_output_as_an_invalid_response() -> None:
    sdk = Mock(spec=AsyncAIStudio)
    sdk.models = ModelsDouble(ModelDouble(text="not json at all"))
    client = YandexAIStudioClient(
        sdk=sdk,
        profile=YandexCompletionProfile(
            model="yandexgpt",
            model_version="rc",
            temperature=0.37,
            max_tokens=3719,
            request_timeout_seconds=73,
            system_prompt="Return mortality JSON",
        ),
        response_type=CompletionResult,
    )

    with pytest.raises(CompletionFailure) as failure:
        await client.complete(user_prompt="Doomed")

    assert (failure.value.provider, failure.value.kind) == (
        "yandex",
        CompletionErrorKind.INVALID_RESPONSE,
    ), "unparseable Yandex output did not surface as an invalid-response failure"
