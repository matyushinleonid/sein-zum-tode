class PayloadRepositoryError(Exception):
    pass


class InvalidStoredPayloadError(Exception):
    pass


class TelegramDeliveryError(Exception):
    pass


class PermanentTelegramDeliveryError(TelegramDeliveryError):
    pass
