import json
import logging
import sys
from unittest.mock import Mock

import pytest

from sein_zum_tode.log_config import (
    ConsoleLogFormatter,
    JsonLogFormatter,
    configure_logging,
)


def log_record() -> logging.LogRecord:
    record = logging.LogRecord(
        name="sein_zum_tode.bot.activities",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Telegram response delivered",
        args=(),
        exc_info=None,
    )
    record.event = "telegram_response_delivered"
    record.component = "worker"
    record.user_id = 40
    record.update_key = "telegram:updates:42:17"
    record.duration_ms = 12.5
    return record


def test_json_formatter_emits_structured_fields() -> None:
    payload = json.loads(JsonLogFormatter("telegram-worker").format(log_record()))

    assert payload["level"] == "INFO"
    assert payload["service"] == "telegram-worker"
    assert payload["message"] == "Telegram response delivered"
    assert payload["event"] == "telegram_response_delivered"
    assert payload["component"] == "worker"
    assert payload["user_id"] == 40
    assert payload["update_key"] == "telegram:updates:42:17"
    assert payload["duration_ms"] == 12.5


def test_console_formatter_emits_readable_structured_fields() -> None:
    rendered = ConsoleLogFormatter("telegram-worker").format(log_record())

    assert "INFO service=telegram-worker" in rendered
    assert "Telegram response delivered" in rendered
    assert "event=telegram_response_delivered" in rendered
    assert "component=worker" in rendered
    assert "user_id=40" in rendered
    assert "update_key=telegram:updates:42:17" in rendered
    assert "duration_ms=12.5" in rendered


@pytest.mark.parametrize(
    ("log_format", "formatter_type"),
    [
        ("console", ConsoleLogFormatter),
        ("json", JsonLogFormatter),
    ],
)
def test_configure_logging_uses_stdout(
    monkeypatch,
    log_format: str,
    formatter_type: type[logging.Formatter],
) -> None:
    basic_config = Mock()
    monkeypatch.setattr(logging, "basicConfig", basic_config)

    configure_logging("INFO", log_format, "telegram-worker")

    handler = basic_config.call_args.kwargs["handlers"][0]
    assert handler.stream is sys.stdout
    assert isinstance(handler.formatter, formatter_type)
    assert basic_config.call_args.kwargs["level"] == "INFO"
    assert basic_config.call_args.kwargs["force"] is True
