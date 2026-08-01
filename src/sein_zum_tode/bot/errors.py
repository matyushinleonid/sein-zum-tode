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
    "TelegramRecipientUnavailableError",
]


class ContentConfigurationError(Exception):
    pass


class TelegramDeliveryError(Exception):
    pass


class PermanentTelegramDeliveryError(TelegramDeliveryError):
    pass


class TelegramRecipientUnavailableError(PermanentTelegramDeliveryError):
    pass
