from typing import Any

from pydantic import BaseModel

from sein_zum_tode.prediction.config import YandexPredictionConfig


class YandexAIStudioClient:
    def __init__(
        self,
        *,
        sdk: Any,
        config: YandexPredictionConfig,
    ) -> None:
        self._config = config
        self._model = sdk.models.completions(
            config.model,
            model_version=config.model_version,
        )

    async def complete[ResponseT: BaseModel](
        self,
        *,
        user_prompt: str,
        response_format: type[ResponseT],
    ) -> ResponseT:
        model = self._model.configure(
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            response_format=response_format,
        )
        result = await model.run(
            [
                {
                    "role": "system",
                    "text": self._config.system_prompt,
                },
                {"role": "user", "text": user_prompt},
            ],
            timeout=self._config.request_timeout_seconds,
        )
        return response_format.model_validate_json(result.text)
