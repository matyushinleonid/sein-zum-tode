import pytest
from pydantic import BaseModel, Field
from redis.exceptions import ConnectionError

from sein_zum_tode.infrastructure.redis_documents import (
    DocumentStoreError,
    InvalidStoredDocumentError,
    PydanticJsonCodec,
    RedisJsonDocumentStore,
    RedisKeyCleaner,
)
from tests.support import RedisDouble

pytestmark = pytest.mark.fast


class Document(BaseModel):
    identity: int = Field(alias="id")
    optional: str | None = None


def document() -> Document:
    return Document.model_validate({"id": 1723})


def test_encodes_pydantic_documents_with_configured_json_options() -> None:
    codec = PydanticJsonCodec(
        model=Document,
        by_alias=True,
        exclude_none=True,
    )

    actual = codec.encode(document())

    assert actual == '{"id":1723}', "codec ignored aliases or exclusion of absent values"


@pytest.mark.parametrize("as_bytes", [False, True])
async def test_loads_a_typed_document_from_each_redis_text_representation(
    as_bytes: bool,
) -> None:
    expected = document()
    payload = expected.model_dump_json(by_alias=True)
    redis = RedisDouble(
        get_result=payload.encode() if as_bytes else payload,
        set_result=True,
        delete_result=0,
    )
    store = RedisJsonDocumentStore(
        redis=redis.client(),
        codec=PydanticJsonCodec(model=Document),
        document_name="cosmic document",
    )

    actual = await store.load("documents:1733")

    assert actual == expected, "document store changed the typed Redis payload"


async def test_returns_none_after_a_document_ttl_expires() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)
    store = RedisJsonDocumentStore(
        redis=redis.client(),
        codec=PydanticJsonCodec(model=Document),
        document_name="cosmic document",
    )

    actual = await store.load("documents:1741")

    assert actual is None, "document store invented a document for an absent Redis key"


async def test_rejects_a_payload_that_does_not_match_the_document_model() -> None:
    redis = RedisDouble(get_result="{}", set_result=True, delete_result=0)
    store = RedisJsonDocumentStore(
        redis=redis.client(),
        codec=PydanticJsonCodec(model=Document),
        document_name="cosmic document",
    )

    with pytest.raises(InvalidStoredDocumentError) as raised:
        await store.load("documents:1747")

    assert (raised.value.document_name, raised.value.key) == (
        "cosmic document",
        "documents:1747",
    ), "validation failure lost the document type or Redis key"


async def test_stores_encoded_documents_with_the_supplied_ttl() -> None:
    expected = document()
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)
    store = RedisJsonDocumentStore(
        redis=redis.client(),
        codec=PydanticJsonCodec(model=Document),
        document_name="cosmic document",
    )

    await store.store("documents:1753", expected, 1759)

    assert redis.events == [("set", "documents:1753", expected.model_dump_json(), 1759)], (
        "document store changed the key, JSON, or TTL"
    )


@pytest.mark.parametrize("operation", ["load", "store"])
async def test_translates_each_redis_document_operation_failure(operation: str) -> None:
    failure = ConnectionError(f"{operation} orbit collapsed")
    redis = RedisDouble(
        get_result=failure if operation == "load" else None,
        set_result=failure if operation == "store" else True,
        delete_result=0,
    )
    store = RedisJsonDocumentStore(
        redis=redis.client(),
        codec=PydanticJsonCodec(model=Document),
        document_name="cosmic document",
    )

    with pytest.raises(DocumentStoreError) as raised:
        if operation == "load":
            await store.load("documents:1777")
        else:
            await store.store("documents:1777", document(), 1783)

    assert (
        raised.value.operation,
        raised.value.document_name,
        raised.value.key,
    ) == (
        operation,
        "cosmic document",
        "documents:1777",
    ), "Redis failure lost its document operation context"


async def test_deletes_ephemeral_document_keys_together() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=2)
    cleaner = RedisKeyCleaner(redis.client())

    await cleaner.delete(("documents:1787", "documents:1789"))

    assert redis.events == [("delete", "documents:1787", "documents:1789")], (
        "document cleaner did not delete all keys atomically"
    )


async def test_translates_a_redis_document_cleanup_failure() -> None:
    redis = RedisDouble(
        get_result=None,
        set_result=True,
        delete_result=ConnectionError("cleanup orbit collapsed"),
    )
    cleaner = RedisKeyCleaner(redis.client())

    with pytest.raises(DocumentStoreError) as raised:
        await cleaner.delete(("documents:1801", "documents:1811"))

    assert (
        raised.value.operation,
        raised.value.document_name,
        raised.value.key,
    ) == (
        "delete",
        "ephemeral payloads",
        "documents:1801, documents:1811",
    ), "cleanup failure lost its operation or key context"
