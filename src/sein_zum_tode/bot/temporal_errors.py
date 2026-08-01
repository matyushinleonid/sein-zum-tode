from temporalio.exceptions import ActivityError, ApplicationError

TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE = "TelegramRecipientUnavailable"


def is_telegram_recipient_unavailable(error: ActivityError) -> bool:
    cause = error.cause
    return (
        isinstance(cause, ApplicationError)
        and cause.type == TELEGRAM_RECIPIENT_UNAVAILABLE_ERROR_TYPE
    )
