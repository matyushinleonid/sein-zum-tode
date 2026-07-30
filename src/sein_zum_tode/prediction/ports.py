from typing import Protocol

from pydantic import BaseModel

from sein_zum_tode.prediction.models import (
    DeathPrediction,
    DeathPredictionRequest,
    StoredDeathPrediction,
)


class DeathPredictor(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def consumes_quota(self) -> bool: ...

    async def predict(self, request: DeathPredictionRequest) -> DeathPrediction: ...


class DeathPredictionRepository(Protocol):
    async def load(self, key: str) -> StoredDeathPrediction | None: ...

    async def store(
        self,
        key: str,
        prediction: StoredDeathPrediction,
        ttl_seconds: int,
    ) -> None: ...


class StructuredCompletionClient(Protocol):
    async def complete[ResponseT: BaseModel](
        self,
        *,
        user_prompt: str,
        response_format: type[ResponseT],
    ) -> ResponseT: ...
