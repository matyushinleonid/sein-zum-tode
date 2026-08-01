from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from pydantic import SecretStr

import sein_zum_tode.bot.worker as worker_module
import sein_zum_tode.main as ingress_module
from sein_zum_tode.prediction.config import (
    DeathPredictionConfig,
    MockPredictionConfig,
    PredictionConfigurationError,
    PredictionProvider,
    YandexPredictionConfig,
)
from tests.assembly import (
    EntrypointAssembly,
    IngressAssembly,
    WorkerAssembly,
    explicit_settings,
)
from tests.support import BotContents

pytestmark = pytest.mark.fast


def yandex_prediction_config() -> DeathPredictionConfig:
    return DeathPredictionConfig(
        provider=PredictionProvider.YANDEX,
        mock=MockPredictionConfig(days_left=17),
        yandex=YandexPredictionConfig(
            model="yandexgpt",
            model_version="rc",
            system_prompt="Return structured data",
        ),
    )


async def test_assembles_and_closes_the_ingress_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembly = IngressAssembly()
    assembly.install(monkeypatch, ingress_module)

    await ingress_module.run(explicit_settings())

    assert assembly.events == [
        ("signals", False),
        ("bot", "181:irregular-token"),
        (
            "redis",
            {
                "host": "redis-pulsar.internal",
                "port": 1861,
                "db": 13,
                "password": "redis-irregular-1867",
            },
        ),
        ("redis_client", True),
        (
            "temporal",
            "temporal-nebula.internal:1831",
            {"namespace": "galactic-1837", "tls": True},
        ),
        ("source", 43, 59),
        ("resolver",),
        ("store", 1871, 1823),
        ("starter", 1871, "telegram-quasars-1847", 1801, 1877),
        ("handoff", True),
        ("waiter", 0.73, 18.29),
        ("poller", ("source", "store", "handoff", "retry_waiter")),
        ("poller.run", False),
        ("bot.close",),
        ("redis.close",),
    ], "ingress composition root wired wrong settings or leaked a client"


async def test_assembles_and_closes_the_temporal_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembly = WorkerAssembly()
    assembly.install(monkeypatch, worker_module)

    await worker_module.run(explicit_settings())

    assert assembly.events == [
        ("signals", False),
        ("content_loader", Path("config/cosmos-content.yaml")),
        ("content.load",),
        ("prediction_config_loader", Path("config/death-prediction.yaml")),
        ("prediction_config.load",),
        ("predictor", True, True),
        ("bot", "181:irregular-token"),
        (
            "redis",
            {
                "host": "redis-pulsar.internal",
                "port": 1861,
                "db": 13,
                "password": "redis-irregular-1867",
            },
        ),
        ("redis_client", True),
        (
            "temporal",
            "temporal-nebula.internal:1831",
            {"namespace": "galactic-1837", "tls": True},
        ),
        ("payloads", True),
        ("conversations", True),
        ("predictions", True),
        (
            "postgres",
            {
                "host": "postgres-orbit.internal",
                "port": 1871,
                "database": "mortals_1873",
                "user": "mortal_1877",
                "password": "postgres-irregular-1879",
                "ssl": True,
                "pgbouncer": True,
            },
        ),
        ("mortals", True),
        (
            "schedules",
            True,
            1871,
            "telegram-quasars-1847",
            1801,
        ),
        ("sender", True),
        ("inspect", True),
        ("prepare", 1823, True, True),
        ("start_conversation", True, True, True, True, 1877, 1823, 3678),
        ("record_answer", True, True, True, 1877, 1823, 3678),
        ("delivery", True, True),
        ("cleanup", True),
        ("mortal_activities", True, True),
        (
            "configure_notifications",
            (
                "updates",
                "responses",
                "mortals",
                "schedules",
                "content",
                "response_ttl_seconds",
            ),
        ),
        (
            "configure_localization",
            (
                "updates",
                "responses",
                "mortals",
                "content",
                "response_ttl_seconds",
            ),
        ),
        (
            "generate_prediction",
            ("predictor", "predictions", "conversations", "mortals", "ttl_seconds"),
        ),
        (
            "apply_prediction",
            (
                "predictions",
                "mortals",
                "schedules",
                "responses",
                "response_ttl_seconds",
            ),
        ),
        (
            "prediction_failure",
            ("mortals", "responses", "content", "response_ttl_seconds"),
        ),
        ("prepare_notification", True, True, True, 1823),
        (
            "worker",
            True,
            "telegram-quasars-1847",
            (
                "TelegramUserWorkflow",
                "TelegramConversationWorkflow",
                "MortalNotificationWorkflow",
            ),
            (
                "activity:inspect",
                "activity:prepare_echo",
                "activity:prepare_help",
                "activity:prepare_about",
                "activity:prepare_localization",
                "activity:prepare_notifications",
                "activity:prepare_limit_exhausted",
                "activity:prepare_unsupported",
                "activity:prepare_group_unsupported",
                "activity:start",
                "activity:record",
                "activity:deliver",
                "activity:cleanup",
                "activity:ensure",
                "activity:reset",
                "activity:has_quota",
                "activity:deactivate",
                "activity:delete_schedule",
                "activity:prepare",
                "activity:configure",
                "activity:configure",
                "activity:generate",
                "activity:apply",
                "activity:prepare",
            ),
        ),
        ("worker.enter",),
        ("worker.exit", None),
        ("bot.close",),
        ("redis.close",),
        ("postgres.close",),
    ], "worker composition root wired wrong Activities or leaked a client"


def test_builds_a_yandex_predictor_only_with_complete_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    sdk = object()
    client = object()
    predictor = object()

    def create_sdk(**options: object) -> object:
        events.append(("sdk", options))
        return sdk

    def create_client(**options: object) -> object:
        events.append(("client", options))
        return client

    def create_predictor(**options: object) -> object:
        events.append(("predictor", options))
        return predictor

    monkeypatch.setattr(worker_module, "AsyncAIStudio", create_sdk)
    monkeypatch.setattr(worker_module, "YandexAIStudioClient", create_client)
    monkeypatch.setattr(worker_module, "YandexDeathPredictor", create_predictor)
    settings = explicit_settings().model_copy(
        update={
            "yandex_ai_studio_api_key": SecretStr("api-key-191"),
            "yandex_ai_studio_folder_id": "folder-193",
        }
    )

    actual = worker_module.create_death_predictor(
        config=yandex_prediction_config(),
        content=BotContents.debug(),
        settings=settings,
    )
    client_options = cast(dict[str, object], events[1][1])
    predictor_options = cast(dict[str, object], events[2][1])

    assert (
        actual is predictor,
        events[0],
        client_options["sdk"] is sdk,
        predictor_options["client"] is client,
    ) == (
        True,
        (
            "sdk",
            {
                "folder_id": "folder-193",
                "auth": "api-key-191",
                "enable_server_data_logging": False,
            },
        ),
        True,
        True,
    )


def test_rejects_yandex_provider_without_credentials() -> None:
    with pytest.raises(PredictionConfigurationError):
        worker_module.create_death_predictor(
            config=yandex_prediction_config(),
            content=BotContents.debug(),
            settings=explicit_settings(),
        )


@pytest.mark.parametrize("module", [ingress_module, worker_module])
def test_configures_and_runs_each_process_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
) -> None:
    assembly = EntrypointAssembly(explicit_settings())
    assembly.install(monkeypatch, module)

    module.main()

    assert assembly.events == [
        ("settings",),
        ("logging", "WARNING", "json", "telegram-cosmos-1811"),
        ("run", True),
    ], "process entrypoint skipped settings, logging, or its async application"
