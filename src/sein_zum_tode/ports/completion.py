from collections.abc import Awaitable
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class CompletionErrorKind(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    BAD_REQUEST = "bad_request"
    SERVER_ERROR = "server_error"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class CompletionFailure(Exception):
    def __init__(self, *, provider: str, kind: CompletionErrorKind) -> None:
        super().__init__(f"{provider} completion failed with {kind.value}")
        self.provider = provider
        self.kind = kind

    @staticmethod
    def kind_of(error: Exception) -> CompletionErrorKind:
        if isinstance(error, CompletionFailure):
            return error.kind
        return CompletionErrorKind.UNKNOWN


class CompletionClient[ResponseT: BaseModel](Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def consumes_quota(self) -> bool: ...

    def complete(self, *, user_prompt: str) -> Awaitable[ResponseT]: ...

    def close(self) -> Awaitable[None]: ...
