from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Update
from redis.exceptions import ConnectionError

from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.redis import RedisTelegramPayloadRepository


def redis_mock() -> SimpleNamespace:
    return SimpleNamespace(
        get=AsyncMock(),
        set=AsyncMock(),
        delete=AsyncMock(),
    )


async def test_repository_loads_update_from_bytes() -> None:
    redis = redis_mock()
    redis.get.return_value = b'{"update_id":17}'
    repository = RedisTelegramPayloadRepository(redis)

    assert await repository.load_update("update-key") == Update(update_id=17)


async def test_repository_returns_none_for_missing_update() -> None:
    redis = redis_mock()
    redis.get.return_value = None
    repository = RedisTelegramPayloadRepository(redis)

    assert await repository.load_update("update-key") is None


async def test_repository_rejects_invalid_update() -> None:
    redis = redis_mock()
    redis.get.return_value = "{}"
    repository = RedisTelegramPayloadRepository(redis)

    with pytest.raises(InvalidStoredPayloadError, match="update-key"):
        await repository.load_update("update-key")


async def test_repository_stores_response_with_ttl() -> None:
    redis = redis_mock()
    redis.set.return_value = True
    repository = RedisTelegramPayloadRepository(redis)
    response = TelegramResponse(chat_id=30, text="sensitive")

    await repository.store_response("response-key", response, 600)

    redis.set.assert_awaited_once_with(
        "response-key",
        response.model_dump_json(),
        ex=600,
    )


async def test_repository_raises_when_response_is_not_stored() -> None:
    redis = redis_mock()
    redis.set.return_value = None
    repository = RedisTelegramPayloadRepository(redis)

    with pytest.raises(PayloadRepositoryError, match="did not store"):
        await repository.store_response(
            "response-key",
            TelegramResponse(chat_id=30, text="response"),
            600,
        )


async def test_repository_wraps_response_store_error() -> None:
    redis = redis_mock()
    redis.set.side_effect = ConnectionError("unavailable")
    repository = RedisTelegramPayloadRepository(redis)

    with pytest.raises(PayloadRepositoryError, match="Failed to store"):
        await repository.store_response(
            "response-key",
            TelegramResponse(chat_id=30, text="response"),
            600,
        )


async def test_repository_loads_response_from_text() -> None:
    redis = redis_mock()
    response = TelegramResponse(chat_id=30, text="response")
    redis.get.return_value = response.model_dump_json()
    repository = RedisTelegramPayloadRepository(redis)

    assert await repository.load_response("response-key") == response


async def test_repository_returns_none_for_missing_response() -> None:
    redis = redis_mock()
    redis.get.return_value = None
    repository = RedisTelegramPayloadRepository(redis)

    assert await repository.load_response("response-key") is None


async def test_repository_rejects_invalid_response() -> None:
    redis = redis_mock()
    redis.get.return_value = "{}"
    repository = RedisTelegramPayloadRepository(redis)

    with pytest.raises(InvalidStoredPayloadError, match="response-key"):
        await repository.load_response("response-key")


async def test_repository_deletes_payloads() -> None:
    redis = redis_mock()
    redis.delete.return_value = 2
    repository = RedisTelegramPayloadRepository(redis)

    await repository.delete(("update-key", "response-key"))

    redis.delete.assert_awaited_once_with("update-key", "response-key")


async def test_repository_wraps_delete_error() -> None:
    redis = redis_mock()
    redis.delete.side_effect = ConnectionError("unavailable")
    repository = RedisTelegramPayloadRepository(redis)

    with pytest.raises(PayloadRepositoryError, match="Failed to delete"):
        await repository.delete(("update-key", "response-key"))


async def test_repository_wraps_read_error() -> None:
    redis = redis_mock()
    redis.get.side_effect = ConnectionError("unavailable")
    repository = RedisTelegramPayloadRepository(redis)

    with pytest.raises(PayloadRepositoryError, match="Failed to load"):
        await repository.load_update("update-key")


async def test_repository_rejects_unexpected_read_response() -> None:
    redis = redis_mock()
    redis.get.return_value = object()
    repository = RedisTelegramPayloadRepository(redis)

    with pytest.raises(TypeError, match="Unexpected Redis GET response"):
        await repository.load_update("update-key")
