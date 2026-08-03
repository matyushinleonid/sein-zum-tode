from sein_zum_tode.infrastructure.redis_documents import (
    DocumentStoreError as PayloadRepositoryError,
)
from sein_zum_tode.infrastructure.redis_documents import (
    InvalidStoredDocumentError as InvalidStoredPayloadError,
)

__all__ = [
    "ContentConfigurationError",
    "InvalidStoredPayloadError",
    "PayloadRepositoryError",
    "PermanentTelegramDeliveryError",
    "TelegramDeliveryError",
    "TelegramRateLimitedError",
    "TelegramRecipientUnavailableError",
]


class ContentConfigurationError(Exception):
    pass


class TelegramDeliveryError(Exception):
    pass


class TelegramRateLimitedError(TelegramDeliveryError):
    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__(f"Telegram rate limit requires retry after {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds


class PermanentTelegramDeliveryError(TelegramDeliveryError):
    pass


class TelegramRecipientUnavailableError(PermanentTelegramDeliveryError):
    pass
