import pytest
from redis.exceptions import ConnectionError

from sein_zum_tode.bot.errors import InvalidStoredPayloadError, PayloadRepositoryError
from sein_zum_tode.prediction.models import StoredDeathPrediction
from sein_zum_tode.prediction.redis import RedisDeathPredictionRepository
from tests.support import RedisDouble

pytestmark = pytest.mark.fast


def prediction() -> StoredDeathPrediction:
    return StoredDeathPrediction.model_validate(
        {
            "request_id": "request-3643",
            "provider": "mock",
            "consumes_quota": False,
            "current_date": "2026-07-30",
            "prediction": {
                "days_left": 3647,
                "message": "Mock prediction",
            },
        }
    )


@pytest.mark.parametrize("as_bytes", [False, True])
async def test_loads_a_stored_prediction(as_bytes: bool) -> None:
    expected = prediction()
    payload = expected.model_dump_json()
    redis = RedisDouble(
        get_result=payload.encode() if as_bytes else payload,
        set_result=True,
        delete_result=0,
    )

    actual = await RedisDeathPredictionRepository(redis.client()).load("prediction:3643")

    assert actual == expected


async def test_returns_none_for_an_expired_prediction() -> None:
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)

    actual = await RedisDeathPredictionRepository(redis.client()).load("prediction:3659")

    assert actual is None


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ("{}", InvalidStoredPayloadError),
        (ConnectionError("redis unavailable"), PayloadRepositoryError),
    ],
)
async def test_rejects_invalid_or_unavailable_prediction(
    payload: object,
    error: type[Exception],
) -> None:
    redis = RedisDouble(get_result=payload, set_result=True, delete_result=0)

    with pytest.raises(error):
        await RedisDeathPredictionRepository(redis.client()).load("prediction:3671")


async def test_stores_prediction_with_the_conversation_ttl() -> None:
    expected = prediction()
    redis = RedisDouble(get_result=None, set_result=True, delete_result=0)

    await RedisDeathPredictionRepository(redis.client()).store(
        "prediction:3673",
        expected,
        3677,
    )

    assert redis.events == [("set", "prediction:3673", expected.model_dump_json(), 3677)]


async def test_translates_a_prediction_store_failure() -> None:
    redis = RedisDouble(
        get_result=None,
        set_result=ConnectionError("redis unavailable"),
        delete_result=0,
    )

    with pytest.raises(PayloadRepositoryError):
        await RedisDeathPredictionRepository(redis.client()).store(
            "prediction:3691",
            prediction(),
            3697,
        )
