from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from httpx import URL
from pydantic import SecretStr

import sein_zum_tode.main as ingress_module
import sein_zum_tode.worker as worker_module
from sein_zum_tode.bot.models import TelegramKeyboardMode
from sein_zum_tode.infrastructure.completion_config import (
    CompletionProvider,
    OpenAICompletionConfig,
    YandexCompletionConfig,
)
from sein_zum_tode.infrastructure.openai import OpenAICompletionProfile
from sein_zum_tode.infrastructure.yandex_ai import YandexCompletionProfile
from sein_zum_tode.notifications.custom_schedule.config import (
    MockNotificationScheduleConfig,
    NotificationPresets,
    NotificationScheduleConfig,
    NotificationScheduleConfigurationError,
)
from sein_zum_tode.notifications.models import NotificationFrequency
from sein_zum_tode.prediction.config import (
    DeathPredictionConfig,
    MockPredictionConfig,
    PredictionConfigurationError,
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
        provider=CompletionProvider.YANDEX,
        system_prompt="Return structured data",
        mock=MockPredictionConfig(days_left=17),
        yandex=YandexCompletionConfig(
            model="yandexgpt",
            model_version="rc",
        ),
        openai=OpenAICompletionConfig(model="gpt-5.6-sol"),
    )


def openai_prediction_config() -> DeathPredictionConfig:
    return yandex_prediction_config().model_copy(update={"provider": CompletionProvider.OPENAI})


def notification_schedule_config(
    provider: CompletionProvider,
) -> NotificationScheduleConfig:
    return NotificationScheduleConfig(
        default_timezone="Europe/Moscow",
        default_frequency=NotificationFrequency.DAILY,
        presets=NotificationPresets(
            daily="0 9 * * *",
            weekly="0 9 * * 1",
            monthly="0 9 1 * *",
            never=None,
        ),
        provider=provider,
        minimum_interval_hours=20,
        system_prompt="Return a localized structured schedule",
        mock=MockNotificationScheduleConfig(
            cron="0 12 * * *",
            timezone=None,
        ),
        yandex=YandexCompletionConfig(
            model="aliceai-llm",
            model_version="latest",
            max_tokens=701,
        ),
        openai=OpenAICompletionConfig(
            model="gpt-5.6-sol",
            max_output_tokens=709,
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
        ("metrics", "ingress"),
        ("bot", "181:irregular-token"),
        (
            "redis",
            {
                "host": "redis-pulsar.internal",
                "port": 1861,
                "database": 13,
                "username": "redis-mortal",
                "password": "redis-irregular-1867",
                "socket_connect_timeout_seconds": 3.7,
                "socket_timeout_seconds": 5.9,
                "max_connections": 29,
                "health_check_interval_seconds": 31,
                "tls": True,
                "tls_verify": True,
                "tls_ca_file": Path("/tls/redis/ca.crt"),
                "tls_certificate_file": Path("/tls/redis/tls.crt"),
                "tls_private_key_file": Path("/tls/redis/tls.key"),
            },
        ),
        ("redis_client", True),
        (
            "temporal_tls",
            {
                "enabled": True,
                "server_name": "temporal-nebula.internal",
                "ca_file": Path("/tls/temporal/ca.crt"),
                "certificate_file": Path("/tls/temporal/tls.crt"),
                "private_key_file": Path("/tls/temporal/tls.key"),
            },
        ),
        (
            "temporal",
            "temporal-nebula.internal:1831",
            {"namespace": "galactic-1837", "tls": "temporal-tls"},
        ),
        ("source", 43, 59),
        ("codec", "Update", True, True),
        ("documents", "Telegram update"),
        ("resolver",),
        ("store", True, 1871, 1823),
        ("temporal_adapter", True),
        ("starter", True, 1871, "telegram-quasars-1847", 1801, 1877, 73),
        ("handoff", True),
        ("whitelist", True, frozenset({181_091, 181_093})),
        ("waiter", 0.73, 18.29),
        ("poller", ("source", "store", "handoff", "retry_waiter", "health")),
        ("metrics.start", "127.0.0.19", 8191, True),
        ("health.start", "127.0.0.23", 8192),
        ("poller.run", False),
        ("health.close",),
        ("metrics.close",),
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
        ("metrics", "worker"),
        ("content_loader", Path("config/cosmos-content.yaml")),
        ("content.load",),
        ("prediction_config_loader", Path("config/death-prediction.yaml")),
        ("prediction_config.load",),
        (
            "notification_schedule_config_loader",
            Path("config/notification-schedule.yaml"),
        ),
        ("notification_schedule_config.load",),
        ("keyboards", True, True, TelegramKeyboardMode.REPLY),
        ("predictor", True, True),
        ("schedule_interpreter", True, True),
        ("bot", "181:irregular-token"),
        (
            "redis",
            {
                "host": "redis-pulsar.internal",
                "port": 1861,
                "database": 13,
                "username": "redis-mortal",
                "password": "redis-irregular-1867",
                "socket_connect_timeout_seconds": 3.7,
                "socket_timeout_seconds": 5.9,
                "max_connections": 29,
                "health_check_interval_seconds": 31,
                "tls": True,
                "tls_verify": True,
                "tls_ca_file": Path("/tls/redis/ca.crt"),
                "tls_certificate_file": Path("/tls/redis/tls.crt"),
                "tls_private_key_file": Path("/tls/redis/tls.key"),
            },
        ),
        ("redis_client", True),
        (
            "temporal_tls",
            {
                "enabled": True,
                "server_name": "temporal-nebula.internal",
                "ca_file": Path("/tls/temporal/ca.crt"),
                "certificate_file": Path("/tls/temporal/tls.crt"),
                "private_key_file": Path("/tls/temporal/tls.key"),
            },
        ),
        (
            "temporal",
            "temporal-nebula.internal:1831",
            {"namespace": "galactic-1837", "tls": "temporal-tls"},
        ),
        ("codec", "Update"),
        ("documents", "Telegram update", True, "Update"),
        ("codec", "TelegramResponse"),
        ("documents", "Telegram response", True, "TelegramResponse"),
        ("codec", "QuestionnaireState"),
        ("documents", "Telegram questionnaire", True, "QuestionnaireState"),
        ("codec", "StoredDeathPrediction"),
        ("documents", "death prediction", True, "StoredDeathPrediction"),
        ("codec", "StoredNotificationScheduleProposal"),
        (
            "documents",
            "notification schedule proposal",
            True,
            "StoredNotificationScheduleProposal",
        ),
        ("codec", "UnsupportedUpdateSession"),
        (
            "documents",
            "unsupported Telegram update session",
            True,
            "UnsupportedUpdateSession",
        ),
        ("cleaner", True),
        (
            "postgres",
            {
                "host": "postgres-orbit.internal",
                "port": 1871,
                "database": "mortals_1873",
                "user": "mortal_1877",
                "password": "postgres-irregular-1879",
                "tls_mode": "verify-full",
                "tls_ca_file": Path("/tls/postgres/ca.crt"),
                "tls_certificate_file": Path("/tls/postgres/tls.crt"),
                "tls_private_key_file": Path("/tls/postgres/tls.key"),
                "pgbouncer": True,
                "connect_timeout_seconds": 7.1,
                "pool_size": 7,
                "max_overflow": 11,
                "pool_timeout_seconds": 13.0,
                "pool_recycle_seconds": 179,
            },
        ),
        ("mortals", True, "Asia/Tokyo", "17 8 * * *"),
        (
            "schedules",
            True,
            1871,
            "telegram-quasars-1847",
            1801,
        ),
        ("sender", True),
        ("inspect", True, True, frozenset({181_081, 181_087})),
        ("prepare", True, 1823, True, True, True),
        ("prepare_unsupported", True, True, True, True, True, 1871, 1811, 1823),
        ("start_questionnaire", True, True, True, True, 1877, 1823, 3678),
        ("record_answer", True, True, True, 1877, 1823, 3678),
        ("delivery", True, True),
        ("cleanup", True),
        ("list_scream_recipients", True),
        ("deliver_scream", True),
        ("scream_report", True, 1823),
        ("mortal_activities", True, True),
        (
            "configure_notifications",
            (
                "updates",
                "responses",
                "mortals",
                "schedules",
                "content",
                "presets",
                "keyboards",
                "response_ttl_seconds",
            ),
        ),
        (
            "generate_notification_schedule",
            (
                "interpreter",
                "proposals",
                "updates",
                "mortals",
                "default_locale",
                "ttl_seconds",
            ),
        ),
        (
            "apply_notification_schedule",
            (
                "proposals",
                "responses",
                "mortals",
                "schedules",
                "validator",
                "presenter",
                "content",
                "response_ttl_seconds",
            ),
        ),
        (
            "notification_schedule_failure",
            ("mortals", "responses", "content", "response_ttl_seconds"),
        ),
        (
            "configure_localization",
            (
                "updates",
                "responses",
                "mortals",
                "content",
                "keyboards",
                "response_ttl_seconds",
            ),
        ),
        (
            "generate_prediction",
            ("predictor", "predictions", "questionnaires", "mortals", "ttl_seconds"),
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
        ("prepare_notification_sample", True, True, True, True, 1823),
        (
            "worker",
            True,
            "telegram-quasars-1847",
            (
                "TelegramUserWorkflow",
                "TelegramQuestionnaireWorkflow",
                "MortalNotificationWorkflow",
                "TelegramScreamWorkflow",
            ),
            (
                "activity:inspect",
                "activity:prepare_help",
                "activity:prepare_about",
                "activity:prepare_localization",
                "activity:prepare_notifications",
                "activity:prepare_custom_notification",
                "activity:prepare_limit_exhausted",
                "activity:prepare_payload_expired",
                "activity:prepare_unsupported",
                "activity:prepare_group_unsupported",
                "activity:prepare_scream_denied",
                "activity:start",
                "activity:record",
                "activity:deliver",
                "activity:cleanup",
                "activity:list",
                "activity:deliver",
                "activity:prepare",
                "activity:ensure",
                "activity:has_quota",
                "activity:mark_unreachable",
                "activity:delete_schedule",
                "activity:prepare",
                "activity:prepare",
                "activity:configure",
                "activity:configure",
                "activity:generate",
                "activity:apply",
                "activity:prepare",
                "activity:generate",
                "activity:apply",
                "activity:prepare",
            ),
        ),
        ("metrics.start", "127.0.0.19", 8191, True),
        ("health.start", "127.0.0.23", 8192),
        ("worker.enter",),
        ("worker.exit", None),
        ("health.close",),
        ("metrics.close",),
        ("predictor.close",),
        ("schedule_interpreter.close",),
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
    monkeypatch.setattr(worker_module, "LLMDeathPredictor", create_predictor)
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
                "enable_server_data_logging": True,
            },
        ),
        True,
        True,
    )
    assert client_options["profile"] == YandexCompletionProfile(
        model="yandexgpt",
        model_version="rc",
        temperature=0.3,
        max_tokens=1000,
        request_timeout_seconds=180,
        system_prompt="Return structured data",
    ), "composition root did not map prediction settings into a generic Yandex profile"
    assert cast(type[object], client_options["response_type"]).__name__ == "DeathPrediction"


def test_rejects_yandex_provider_without_credentials() -> None:
    with pytest.raises(PredictionConfigurationError):
        worker_module.create_death_predictor(
            config=yandex_prediction_config(),
            content=BotContents.debug(),
            settings=explicit_settings(),
        )


def test_builds_an_openai_predictor_with_mandatory_socks5_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    http_client = object()
    sdk = object()
    sdk_adapter = object()
    completion = object()
    predictor = object()

    def create_http_client(**options: object) -> object:
        events.append(("http", options))
        return http_client

    def create_sdk(**options: object) -> object:
        events.append(("sdk", options))
        return sdk

    def create_sdk_adapter(current_sdk: object) -> object:
        events.append(("sdk_adapter", current_sdk is sdk))
        return sdk_adapter

    def create_completion(**options: object) -> object:
        events.append(("completion", options))
        return completion

    def create_predictor(**options: object) -> object:
        events.append(("predictor", options))
        return predictor

    monkeypatch.setattr(worker_module, "DefaultAsyncHttpxClient", create_http_client)
    monkeypatch.setattr(worker_module, "AsyncOpenAI", create_sdk)
    monkeypatch.setattr(worker_module, "AsyncOpenAISdkAdapter", create_sdk_adapter)
    monkeypatch.setattr(worker_module, "OpenAICompletionClient", create_completion)
    monkeypatch.setattr(worker_module, "LLMDeathPredictor", create_predictor)
    settings = explicit_settings().model_copy(
        update={
            "openai_api_key": SecretStr("openai-key-397"),
            "socks5_proxy_host": "proxy-nebula.internal",
            "socks5_proxy_port": 3989,
            "socks5_proxy_username": "mortal-4001",
            "socks5_proxy_password": SecretStr("proxy-irregular-4003"),
        }
    )

    actual = worker_module.create_death_predictor(
        config=openai_prediction_config(),
        content=BotContents.debug(),
        settings=settings,
    )
    proxy = cast(URL, cast(dict[str, object], events[0][1])["proxy"])
    sdk_options = cast(dict[str, object], events[1][1])
    completion_options = cast(dict[str, object], events[3][1])
    predictor_options = cast(dict[str, object], events[4][1])

    assert (
        actual is predictor,
        proxy.scheme,
        proxy.host,
        proxy.port,
        proxy.username,
        proxy.password,
        sdk_options,
        events[2],
        completion_options["sdk"] is sdk_adapter,
        predictor_options["client"] is completion,
    ) == (
        True,
        "socks5h",
        "proxy-nebula.internal",
        3989,
        "mortal-4001",
        "proxy-irregular-4003",
        {"api_key": "openai-key-397", "http_client": http_client},
        ("sdk_adapter", True),
        True,
        True,
    ), "OpenAI composition did not enforce the authenticated SOCKS5 transport"
    assert completion_options["profile"] == OpenAICompletionProfile(
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        max_output_tokens=1000,
        request_timeout_seconds=180,
        system_prompt="Return structured data",
    )
    assert cast(type[object], completion_options["response_type"]).__name__ == ("DeathPrediction")


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("openai_api_key", None),
        ("socks5_proxy_host", ""),
        ("socks5_proxy_username", ""),
        ("socks5_proxy_password", None),
    ],
)
def test_rejects_openai_provider_without_complete_proxy_credentials(
    setting: str,
    value: object,
) -> None:
    settings = explicit_settings().model_copy(
        update={
            "openai_api_key": SecretStr("openai-key-4013"),
            "socks5_proxy_password": SecretStr("proxy-irregular-4019"),
            setting: value,
        }
    )

    with pytest.raises(PredictionConfigurationError):
        worker_module.create_death_predictor(
            config=openai_prediction_config(),
            content=BotContents.debug(),
            settings=settings,
        )


def test_builds_a_yandex_notification_schedule_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    sdk = object()
    completion = object()
    interpreter = object()

    def create_sdk(**options: object) -> object:
        events.append(("sdk", options))
        return sdk

    def create_completion(**options: object) -> object:
        events.append(("completion", options))
        return completion

    def create_interpreter(**options: object) -> object:
        events.append(("interpreter", options))
        return interpreter

    monkeypatch.setattr(worker_module, "AsyncAIStudio", create_sdk)
    monkeypatch.setattr(worker_module, "YandexAIStudioClient", create_completion)
    monkeypatch.setattr(
        worker_module,
        "LLMNotificationScheduleInterpreter",
        create_interpreter,
    )
    settings = explicit_settings().model_copy(
        update={
            "yandex_ai_studio_api_key": SecretStr("schedule-key-4211"),
            "yandex_ai_studio_folder_id": "schedule-folder-4217",
        }
    )

    actual = worker_module.create_notification_schedule_interpreter(
        config=notification_schedule_config(CompletionProvider.YANDEX),
        content=BotContents.debug(),
        settings=settings,
    )

    completion_options = cast(dict[str, object], events[1][1])
    assert (
        actual is interpreter,
        completion_options["sdk"] is sdk,
        cast(type[object], completion_options["response_type"]).__name__,
        cast(dict[str, object], events[2][1])["client"] is completion,
    ) == (
        True,
        True,
        "NotificationScheduleProposal",
        True,
    )


def test_builds_an_openai_notification_schedule_interpreter_through_socks5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    http = object()
    sdk = object()
    adapter = object()
    completion = object()
    interpreter = object()

    def create_http(**options: object) -> object:
        events.append(("http", options))
        return http

    def create_sdk(**options: object) -> object:
        events.append(("sdk", options))
        return sdk

    def create_adapter(current: object) -> object:
        events.append(("adapter", current))
        return adapter

    def create_completion(**options: object) -> object:
        events.append(("completion", options))
        return completion

    def create_interpreter(**options: object) -> object:
        events.append(("interpreter", options))
        return interpreter

    monkeypatch.setattr(worker_module, "DefaultAsyncHttpxClient", create_http)
    monkeypatch.setattr(worker_module, "AsyncOpenAI", create_sdk)
    monkeypatch.setattr(worker_module, "AsyncOpenAISdkAdapter", create_adapter)
    monkeypatch.setattr(worker_module, "OpenAICompletionClient", create_completion)
    monkeypatch.setattr(
        worker_module,
        "LLMNotificationScheduleInterpreter",
        create_interpreter,
    )
    settings = explicit_settings().model_copy(
        update={
            "openai_api_key": SecretStr("schedule-openai-4229"),
            "socks5_proxy_host": "proxy-schedule.internal",
            "socks5_proxy_port": 4227,
            "socks5_proxy_username": "mortal-schedule-4228",
            "socks5_proxy_password": SecretStr("schedule-proxy-4231"),
        }
    )

    actual = worker_module.create_notification_schedule_interpreter(
        config=notification_schedule_config(CompletionProvider.OPENAI),
        content=BotContents.debug(),
        settings=settings,
    )

    completion_options = cast(dict[str, object], events[3][1])
    assert (
        actual is interpreter,
        cast(dict[str, object], events[1][1])["http_client"] is http,
        events[2] == ("adapter", sdk),
        completion_options["sdk"] is adapter,
        cast(type[object], completion_options["response_type"]).__name__,
        cast(dict[str, object], events[4][1])["client"] is completion,
    ) == (
        True,
        True,
        True,
        True,
        "NotificationScheduleProposal",
        True,
    )


@pytest.mark.parametrize(
    "provider",
    [CompletionProvider.YANDEX, CompletionProvider.OPENAI],
)
def test_rejects_external_schedule_interpreters_without_credentials(
    provider: CompletionProvider,
) -> None:
    with pytest.raises(NotificationScheduleConfigurationError):
        worker_module.create_notification_schedule_interpreter(
            config=notification_schedule_config(provider),
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
