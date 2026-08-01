from collections.abc import Awaitable
from typing import Protocol


class DocumentReader[DocumentT](Protocol):
    def load(self, key: str) -> Awaitable[DocumentT | None]: ...


class DocumentWriter[DocumentT](Protocol):
    def store(
        self,
        key: str,
        document: DocumentT,
        ttl_seconds: int,
    ) -> Awaitable[None]: ...


class DocumentStore[DocumentT](Protocol):
    def load(self, key: str) -> Awaitable[DocumentT | None]: ...

    def store(
        self,
        key: str,
        document: DocumentT,
        ttl_seconds: int,
    ) -> Awaitable[None]: ...
