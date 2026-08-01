from collections.abc import Awaitable
from typing import Protocol

from pydantic import BaseModel


class CompletionClient[ResponseT: BaseModel](Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def consumes_quota(self) -> bool: ...

    def complete(self, *, user_prompt: str) -> Awaitable[ResponseT]: ...
