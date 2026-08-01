from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class YandexCompletionProfile:
    model: str
    model_version: str
    temperature: float
    max_tokens: int
    request_timeout_seconds: int
    system_prompt: str


class YandexAIStudioClient[ResponseT: BaseModel]:
    def __init__(
        self,
        *,
        sdk: Any,
        profile: YandexCompletionProfile,
        response_type: type[ResponseT],
    ) -> None:
        self._profile = profile
        self._response_type = response_type
        self._model = sdk.models.completions(
            profile.model,
            model_version=profile.model_version,
        )

    @property
    def provider_name(self) -> str:
        return "yandex"

    @property
    def consumes_quota(self) -> bool:
        return True

    async def complete(
        self,
        *,
        user_prompt: str,
    ) -> ResponseT:
        model = self._model.configure(
            temperature=self._profile.temperature,
            max_tokens=self._profile.max_tokens,
            response_format=self._response_type,
        )
        result = await model.run(
            [
                {
                    "role": "system",
                    "text": self._profile.system_prompt,
                },
                {"role": "user", "text": user_prompt},
            ],
            timeout=self._profile.request_timeout_seconds,
        )
        return self._response_type.model_validate_json(result.text)

    async def close(self) -> None:
        return None
