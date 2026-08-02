import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

LogFormat = Literal["console", "json"]

_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}
_FIELD_ORDER = (
    "event",
    "component",
    "user_id",
    "correlation_id",
    "session_id",
    "workflow_id",
    "workflow_run_id",
    "update_id",
    "update_key",
    "inspection_kind",
    "chat_id",
)


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")


def _extra_fields(record: logging.LogRecord) -> dict[str, object]:
    return {
        key: value for key, value in record.__dict__.items() if key not in _STANDARD_RECORD_FIELDS
    }


def _ordered_fields(fields: dict[str, object]) -> list[tuple[str, object]]:
    order = {name: index for index, name in enumerate(_FIELD_ORDER)}
    return sorted(fields.items(), key=lambda item: (order.get(item[0], len(order)), item[0]))


def _console_value(value: object) -> str:
    if isinstance(value, str) and value and not any(character.isspace() for character in value):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


class ConsoleLogFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        fields = " ".join(
            f"{key}={_console_value(value)}"
            for key, value in _ordered_fields(_extra_fields(record))
        )
        rendered = (
            f"{_timestamp(record)} {record.levelname} "
            f"service={self._service} logger={record.name} {record.getMessage()}"
        )
        if fields:
            rendered = f"{rendered} {fields}"
        if record.exc_info:
            rendered = f"{rendered}\n{self.formatException(record.exc_info)}"
        return rendered


class JsonLogFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": _timestamp(record),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
            **_extra_fields(record),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def configure_logging(level: str, log_format: LogFormat, service: str) -> None:
    formatter: logging.Formatter
    if log_format == "json":
        formatter = JsonLogFormatter(service)
    else:
        formatter = ConsoleLogFormatter(service)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logging.basicConfig(
        level=level,
        handlers=[handler],
        force=True,
    )
