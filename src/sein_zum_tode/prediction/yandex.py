from sein_zum_tode.prediction.models import DeathPrediction, DeathPredictionRequest
from sein_zum_tode.prediction.ports import DeathPredictor, StructuredCompletionClient


class YandexDeathPredictor(DeathPredictor):
    def __init__(
        self,
        *,
        client: StructuredCompletionClient,
    ) -> None:
        self._client = client

    @property
    def provider_name(self) -> str:
        return "yandex"

    @property
    def consumes_quota(self) -> bool:
        return True

    async def predict(self, request: DeathPredictionRequest) -> DeathPrediction:
        return await self._client.complete(
            user_prompt=request.prompt(),
            response_format=DeathPrediction,
        )
