from sein_zum_tode.bot.content import BotContent
from sein_zum_tode.prediction.config import MockPredictionConfig
from sein_zum_tode.prediction.models import DeathPrediction, DeathPredictionRequest


class MockDeathPredictor:
    def __init__(
        self,
        *,
        config: MockPredictionConfig,
        content: BotContent,
    ) -> None:
        self._config = config
        self._content = content

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def consumes_quota(self) -> bool:
        return False

    async def predict(self, request: DeathPredictionRequest) -> DeathPrediction:
        localized = self._content.localized(request.locale)
        return DeathPrediction(
            prediction_possible=True,
            days_left=self._config.days_left,
            message=localized.prediction.mock_text(request.answers_text()),
        )

    async def close(self) -> None:
        return None
