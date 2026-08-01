from collections.abc import Awaitable
from typing import Protocol

from sein_zum_tode.prediction.models import (
    DeathPrediction,
    DeathPredictionRequest,
)


class DeathPredictor(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def consumes_quota(self) -> bool: ...

    def predict(self, request: DeathPredictionRequest) -> Awaitable[DeathPrediction]: ...

    def close(self) -> Awaitable[None]: ...
