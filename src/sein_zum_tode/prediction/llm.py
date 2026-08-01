from sein_zum_tode.ports.completion import CompletionClient
from sein_zum_tode.prediction.models import DeathPrediction, DeathPredictionRequest


class LLMDeathPredictor:
    def __init__(
        self,
        *,
        client: CompletionClient[DeathPrediction],
    ) -> None:
        self._client = client

    @property
    def provider_name(self) -> str:
        return self._client.provider_name

    @property
    def consumes_quota(self) -> bool:
        return self._client.consumes_quota

    async def predict(self, request: DeathPredictionRequest) -> DeathPrediction:
        return await self._client.complete(user_prompt=request.prompt())

    async def close(self) -> None:
        await self._client.close()
