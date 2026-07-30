class PayloadRepositoryError(Exception):
    pass


class ContentConfigurationError(Exception):
    pass


class InvalidStoredPayloadError(Exception):
    pass


class TelegramDeliveryError(Exception):
    pass


class PermanentTelegramDeliveryError(TelegramDeliveryError):
    pass
