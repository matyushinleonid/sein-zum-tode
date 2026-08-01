from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ValidationError

from sein_zum_tode.infrastructure.redis import RedisClient, RedisClientError


class DocumentStoreError(Exception):
    def __init__(
        self,
        operation: str,
        document_name: str | None = None,
        key: str | None = None,
    ) -> None:
        self.operation = operation
        self.document_name = document_name
        self.key = key
        message = (
            operation
            if document_name is None or key is None
            else f"Failed to {operation} {document_name} at {key}"
        )
        super().__init__(message)


class InvalidStoredDocumentError(Exception):
    def __init__(self, document_name: str, key: str | None = None) -> None:
        self.document_name = document_name
        self.key = key
        message = document_name if key is None else f"Invalid {document_name} at {key}"
        super().__init__(message)


class JsonDocumentCodec[DocumentT](Protocol):
    def encode(self, document: DocumentT) -> str: ...

    def decode(self, payload: str) -> DocumentT: ...


@dataclass(frozen=True, slots=True)
class PydanticJsonCodec[DocumentT: BaseModel]:
    model: type[DocumentT]
    by_alias: bool = False
    exclude_none: bool = False

    def encode(self, document: DocumentT) -> str:
        return document.model_dump_json(
            by_alias=self.by_alias,
            exclude_none=self.exclude_none,
        )

    def decode(self, payload: str) -> DocumentT:
        return self.model.model_validate_json(payload)


class RedisJsonDocumentStore[DocumentT]:
    def __init__(
        self,
        *,
        redis: RedisClient,
        codec: JsonDocumentCodec[DocumentT],
        document_name: str,
    ) -> None:
        self._redis = redis
        self._codec = codec
        self._document_name = document_name

    async def load(self, key: str) -> DocumentT | None:
        try:
            payload = await self._redis.get(key)
        except RedisClientError as error:
            raise DocumentStoreError("load", self._document_name, key) from error
        if payload is None:
            return None
        try:
            return self._codec.decode(payload)
        except ValidationError as error:
            raise InvalidStoredDocumentError(self._document_name, key) from error

    async def store(
        self,
        key: str,
        document: DocumentT,
        ttl_seconds: int,
    ) -> None:
        payload = self._codec.encode(document)
        try:
            await self._redis.set(key, payload, ttl_seconds)
        except RedisClientError as error:
            raise DocumentStoreError("store", self._document_name, key) from error


class RedisKeyCleaner:
    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def delete(self, keys: tuple[str, ...]) -> None:
        try:
            await self._redis.delete(keys)
        except RedisClientError as error:
            raise DocumentStoreError(
                "delete",
                "ephemeral payloads",
                ", ".join(keys),
            ) from error
