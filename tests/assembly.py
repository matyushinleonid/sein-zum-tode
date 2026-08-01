import asyncio
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from pydantic import SecretStr

from sein_zum_tode.config import Settings, WorkerSettings


def explicit_settings() -> WorkerSettings:
    return WorkerSettings.model_construct(
        app_name="telegram-cosmos-1811",
        log_level="WARNING",
        log_format="json",
        telegram_bot_token=SecretStr("181:irregular-token"),
        telegram_polling_timeout_seconds=43,
        telegram_request_timeout_seconds=59,
        telegram_update_ttl_seconds=1823,
        telegram_admin_user_ids=frozenset({181_081, 181_087}),
        questionnaire_ttl_seconds=1877,
        bot_content_path=Path("config/cosmos-content.yaml"),
        retry_initial_delay_seconds=0.73,
        retry_max_delay_seconds=18.29,
        temporal_address="temporal-nebula.internal:1831",
        temporal_namespace="galactic-1837",
        temporal_task_queue="telegram-quasars-1847",
        temporal_tls=True,
        temporal_activity_retry_timeout_seconds=1801,
        redis_host="redis-pulsar.internal",
        redis_port=1861,
        redis_database=13,
        redis_password=SecretStr("redis-irregular-1867"),
        postgres_host="postgres-orbit.internal",
        postgres_port=1871,
        postgres_database="mortals_1873",
        postgres_user="mortal_1877",
        postgres_password=SecretStr("postgres-irregular-1879"),
        postgres_ssl=True,
        postgres_pgbouncer=True,
        yandex_ai_studio_enable_server_data_logging=True,
    )


class ClosableSession:
    def __init__(self, events: list[tuple[object, ...]], name: str) -> None:
        self.events = events
        self.name = name

    async def close(self) -> None:
        self.events.append((f"{self.name}.close",))


class BotResource:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.id = 1871
        self.session = ClosableSession(events, "bot")


class RedisResource:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    async def aclose(self) -> None:
        self.events.append(("redis.close",))


class PostgresResource:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append(("postgres.close",))


class PollerResource:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    async def run(self, stop_event: asyncio.Event) -> None:
        self.events.append(("poller.run", stop_event.is_set()))


class WorkerResource:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    async def __aenter__(self) -> WorkerResource:
        self.events.append(("worker.enter",))
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> None:
        self.events.append(("worker.exit", exception_type))


class IngressAssembly:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.bot = BotResource(self.events)
        self.redis = RedisResource(self.events)
        self.temporal = object()
        self.temporal_adapter = object()
        self.update_documents = object()

    def install(self, monkeypatch: Any, module: Any) -> None:
        monkeypatch.setattr(module, "Bot", self.create_bot)
        monkeypatch.setattr(module, "Redis", self.create_redis)
        monkeypatch.setattr(module, "Client", SimpleNamespace(connect=self.connect_temporal))
        monkeypatch.setattr(module, "AiogramUpdateSource", self.create_source)
        monkeypatch.setattr(module, "RedisClient", self.create_redis_client)
        monkeypatch.setattr(module, "PydanticJsonCodec", self.create_codec)
        monkeypatch.setattr(module, "RedisJsonDocumentStore", self.create_documents)
        monkeypatch.setattr(module, "AiogramUpdateUserResolver", self.create_resolver)
        monkeypatch.setattr(module, "TelegramUpdateStore", self.create_store)
        monkeypatch.setattr(module, "TemporalClientAdapter", self.create_temporal_adapter)
        monkeypatch.setattr(module, "TemporalUserWorkflowStarter", self.create_starter)
        monkeypatch.setattr(module, "TemporalUpdateHandoff", self.create_handoff)
        monkeypatch.setattr(module, "ExponentialRetryWaiter", self.create_waiter)
        monkeypatch.setattr(module, "TelegramPoller", self.create_poller)
        monkeypatch.setattr(module, "install_signal_handlers", self.install_signals)

    def create_bot(self, *, token: str) -> BotResource:
        self.events.append(("bot", token))
        return self.bot

    def create_redis(self, **options: object) -> RedisResource:
        self.events.append(("redis", options))
        return self.redis

    async def connect_temporal(self, address: str, **options: object) -> object:
        self.events.append(("temporal", address, options))
        return self.temporal

    def create_source(self, **options: object) -> object:
        self.events.append(
            (
                "source",
                options["polling_timeout_seconds"],
                options["request_timeout_seconds"],
            )
        )
        return object()

    def create_redis_client(self, redis: object) -> object:
        self.events.append(("redis_client", redis is self.redis))
        return object()

    def create_codec(self, **options: object) -> object:
        model = cast(type[object], options["model"])
        self.events.append(
            (
                "codec",
                model.__name__,
                options.get("by_alias", False),
                options.get("exclude_none", False),
            )
        )
        return object()

    def create_documents(self, **options: object) -> object:
        self.events.append(("documents", options["document_name"]))
        return self.update_documents

    def create_resolver(self) -> object:
        self.events.append(("resolver",))
        return object()

    def create_store(self, **options: object) -> object:
        self.events.append(
            (
                "store",
                options["updates"] is self.update_documents,
                options["bot_id"],
                options["ttl_seconds"],
            )
        )
        return object()

    def create_temporal_adapter(self, client: object) -> object:
        self.events.append(("temporal_adapter", client is self.temporal))
        return self.temporal_adapter

    def create_starter(self, **options: object) -> object:
        self.events.append(
            (
                "starter",
                options["client"] is self.temporal_adapter,
                options["bot_id"],
                options["task_queue"],
                options["activity_retry_timeout_seconds"],
                options["questionnaire_ttl_seconds"],
            )
        )
        return object()

    def create_handoff(self, starter: object) -> object:
        self.events.append(("handoff", starter.__class__ is object))
        return object()

    def create_waiter(self, **options: object) -> object:
        self.events.append(
            (
                "waiter",
                options["initial_delay_seconds"],
                options["max_delay_seconds"],
            )
        )
        return object()

    def create_poller(self, **options: object) -> PollerResource:
        self.events.append(("poller", tuple(options)))
        return PollerResource(self.events)

    def install_signals(self, stop_event: asyncio.Event) -> None:
        self.events.append(("signals", stop_event.is_set()))


class ActivityDefinitions:
    def __init__(self, names: tuple[str, ...]) -> None:
        for name in names:
            setattr(self, name, f"activity:{name}")


class ContentResource:
    def default(self) -> object:
        return SimpleNamespace(help="Chart the irregular constellations")


class ContentLoaderResource:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        content: ContentResource,
    ) -> None:
        self.events = events
        self.content = content

    def load(self) -> ContentResource:
        self.events.append(("content.load",))
        return self.content


class PredictionConfigLoaderResource:
    def __init__(self, events: list[tuple[object, ...]], config: object) -> None:
        self.events = events
        self.config = config

    def load(self) -> object:
        self.events.append(("prediction_config.load",))
        return self.config


class WorkerAssembly:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.bot = BotResource(self.events)
        self.redis = RedisResource(self.events)
        self.redis_client = object()
        self.postgres = PostgresResource(self.events)
        self.temporal = object()
        self.update_documents = object()
        self.response_documents = object()
        self.questionnaires = object()
        self.predictions = object()
        self.cleaner = object()
        self.mortals = object()
        self.schedules = object()
        self.sender = object()
        self.content = ContentResource()
        self.prediction_config = SimpleNamespace(
            provider="mock",
            mock=object(),
            yandex=object(),
        )
        self.predictor = object()

    def install(self, monkeypatch: Any, module: Any) -> None:
        monkeypatch.setattr(module, "Bot", self.create_bot)
        monkeypatch.setattr(module, "Redis", self.create_redis)
        monkeypatch.setattr(module, "RedisClient", self.create_redis_client)
        monkeypatch.setattr(module, "PydanticJsonCodec", self.create_codec)
        monkeypatch.setattr(module, "RedisJsonDocumentStore", self.create_documents)
        monkeypatch.setattr(module, "RedisKeyCleaner", self.create_cleaner)
        monkeypatch.setattr(
            module,
            "PostgresClient",
            SimpleNamespace(create=self.create_postgres),
        )
        monkeypatch.setattr(module, "Client", SimpleNamespace(connect=self.connect_temporal))
        monkeypatch.setattr(module, "YamlBotContentLoader", self.create_content_loader)
        monkeypatch.setattr(
            module,
            "YamlDeathPredictionConfigLoader",
            self.create_prediction_config_loader,
        )
        monkeypatch.setattr(module, "PostgresMortalRepository", self.create_mortals)
        monkeypatch.setattr(module, "TemporalMortalSchedule", self.create_schedules)
        monkeypatch.setattr(module, "AiogramTelegramMessageSender", self.create_sender)
        monkeypatch.setattr(module, "MockDeathPredictor", self.create_predictor)
        monkeypatch.setattr(module, "InspectTelegramUpdateActivity", self.create_inspect)
        monkeypatch.setattr(module, "PrepareTelegramResponseActivities", self.create_prepare)
        monkeypatch.setattr(
            module,
            "StartTelegramQuestionnaireActivity",
            self.create_start_questionnaire,
        )
        monkeypatch.setattr(
            module,
            "RecordTelegramQuestionnaireAnswerActivity",
            self.create_record_answer,
        )
        monkeypatch.setattr(module, "DeliverTelegramResponseActivity", self.create_delivery)
        monkeypatch.setattr(module, "CleanupTelegramPayloadsActivity", self.create_cleanup)
        monkeypatch.setattr(
            module,
            "ListScreamRecipientsActivity",
            self.create_list_scream_recipients,
        )
        monkeypatch.setattr(module, "DeliverScreamActivity", self.create_deliver_scream)
        monkeypatch.setattr(
            module,
            "PrepareScreamReportActivity",
            self.create_scream_report,
        )
        monkeypatch.setattr(module, "MortalActivities", self.create_mortal_activities)
        monkeypatch.setattr(
            module,
            "PrepareMortalNotificationActivity",
            self.create_prepare_notification,
        )
        monkeypatch.setattr(
            module,
            "ConfigureMortalNotificationsActivity",
            self.create_configure_notifications,
        )
        monkeypatch.setattr(
            module,
            "ConfigureMortalLocalizationActivity",
            self.create_configure_localization,
        )
        monkeypatch.setattr(
            module,
            "GenerateDeathPredictionActivity",
            self.create_generate_prediction,
        )
        monkeypatch.setattr(
            module,
            "ApplyDeathPredictionActivity",
            self.create_apply_prediction,
        )
        monkeypatch.setattr(
            module,
            "PreparePredictionFailureActivity",
            self.create_prediction_failure,
        )
        monkeypatch.setattr(module, "Worker", self.create_worker)
        monkeypatch.setattr(module, "install_signal_handlers", self.install_signals)

    def create_bot(self, *, token: str) -> BotResource:
        self.events.append(("bot", token))
        return self.bot

    def create_redis(self, **options: object) -> RedisResource:
        self.events.append(("redis", options))
        return self.redis

    def create_redis_client(self, redis: object) -> object:
        self.events.append(("redis_client", redis is self.redis))
        return self.redis_client

    def create_postgres(self, **options: object) -> PostgresResource:
        self.events.append(("postgres", options))
        return self.postgres

    async def connect_temporal(self, address: str, **options: object) -> object:
        self.events.append(("temporal", address, options))
        return self.temporal

    def create_content_loader(self, path: Path) -> ContentLoaderResource:
        self.events.append(("content_loader", path))
        return ContentLoaderResource(self.events, self.content)

    def create_prediction_config_loader(
        self,
        path: Path,
    ) -> PredictionConfigLoaderResource:
        self.events.append(("prediction_config_loader", path))
        return PredictionConfigLoaderResource(self.events, self.prediction_config)

    def create_codec(self, **options: object) -> object:
        model = cast(type[object], options["model"])
        name = model.__name__
        self.events.append(("codec", name))
        return SimpleNamespace(model_name=name)

    def create_documents(self, **options: object) -> object:
        name = cast(str, options["document_name"])
        codec = cast(SimpleNamespace, options["codec"])
        documents = {
            "Telegram update": self.update_documents,
            "Telegram response": self.response_documents,
            "Telegram questionnaire": self.questionnaires,
            "death prediction": self.predictions,
        }[name]
        self.events.append(
            (
                "documents",
                name,
                options["redis"] is self.redis_client,
                codec.model_name,
            )
        )
        return documents

    def create_cleaner(self, redis: object) -> object:
        self.events.append(("cleaner", redis is self.redis_client))
        return self.cleaner

    def create_mortals(self, postgres: object) -> object:
        self.events.append(("mortals", postgres is self.postgres))
        return self.mortals

    def create_schedules(self, **options: object) -> object:
        self.events.append(
            (
                "schedules",
                options["client"] is self.temporal,
                options["bot_id"],
                options["task_queue"],
                options["activity_retry_timeout_seconds"],
            )
        )
        return self.schedules

    def create_sender(self, bot: object) -> object:
        self.events.append(("sender", bot is self.bot))
        return self.sender

    def create_predictor(self, **options: object) -> object:
        self.events.append(
            (
                "predictor",
                options["config"] is self.prediction_config.mock,
                options["content"] is self.content,
            )
        )
        return self.predictor

    def create_inspect(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "inspect",
                options["update_reader"] is self.update_documents,
                options["admin_user_ids"],
            )
        )
        return ActivityDefinitions(("inspect",))

    def create_prepare(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "prepare",
                options["response_store"] is self.response_documents,
                options["ttl_seconds"],
                options["content"] is self.content,
                options["mortals"] is self.mortals,
            )
        )
        return ActivityDefinitions(
            (
                "prepare_help",
                "prepare_about",
                "prepare_localization",
                "prepare_notifications",
                "prepare_limit_exhausted",
                "prepare_unsupported",
                "prepare_group_unsupported",
                "prepare_scream_denied",
            )
        )

    def create_start_questionnaire(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "start_questionnaire",
                options["content"] is self.content,
                options["mortals"] is self.mortals,
                options["questionnaires"] is self.questionnaires,
                options["responses"] is self.response_documents,
                options["questionnaire_ttl_seconds"],
                options["response_ttl_seconds"],
                options["privacy_response_ttl_seconds"],
            )
        )
        return ActivityDefinitions(("start",))

    def create_record_answer(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "record_answer",
                options["updates"] is self.update_documents,
                options["questionnaires"] is self.questionnaires,
                options["responses"] is self.response_documents,
                options["questionnaire_ttl_seconds"],
                options["response_ttl_seconds"],
                options["privacy_response_ttl_seconds"],
            )
        )
        return ActivityDefinitions(("record",))

    def create_delivery(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "delivery",
                options["response_reader"] is self.response_documents,
                options["sender"] is self.sender,
            )
        )
        return ActivityDefinitions(("deliver",))

    def create_cleanup(self, **options: object) -> ActivityDefinitions:
        self.events.append(("cleanup", options["cleaner"] is self.cleaner))
        return ActivityDefinitions(("cleanup",))

    def create_list_scream_recipients(self, **options: object) -> ActivityDefinitions:
        self.events.append(("list_scream_recipients", options["mortals"] is self.mortals))
        return ActivityDefinitions(("list",))

    def create_deliver_scream(self, **options: object) -> ActivityDefinitions:
        self.events.append(("deliver_scream", options["copier"] is self.sender))
        return ActivityDefinitions(("deliver",))

    def create_scream_report(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "scream_report",
                options["responses"] is self.response_documents,
                options["ttl_seconds"],
            )
        )
        return ActivityDefinitions(("prepare",))

    def create_mortal_activities(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "mortal_activities",
                options["mortals"] is self.mortals,
                options["schedules"] is self.schedules,
            )
        )
        return ActivityDefinitions(
            ("ensure", "reset", "has_quota", "deactivate", "delete_schedule")
        )

    def create_prepare_notification(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "prepare_notification",
                options["mortals"] is self.mortals,
                options["responses"] is self.response_documents,
                options["content"] is self.content,
                options["response_ttl_seconds"],
            )
        )
        return ActivityDefinitions(("prepare",))

    def create_configure_notifications(self, **options: object) -> ActivityDefinitions:
        self.events.append(("configure_notifications", tuple(options)))
        return ActivityDefinitions(("configure",))

    def create_configure_localization(self, **options: object) -> ActivityDefinitions:
        self.events.append(("configure_localization", tuple(options)))
        return ActivityDefinitions(("configure",))

    def create_generate_prediction(self, **options: object) -> ActivityDefinitions:
        self.events.append(("generate_prediction", tuple(options)))
        return ActivityDefinitions(("generate",))

    def create_apply_prediction(self, **options: object) -> ActivityDefinitions:
        self.events.append(("apply_prediction", tuple(options)))
        return ActivityDefinitions(("apply",))

    def create_prediction_failure(self, **options: object) -> ActivityDefinitions:
        self.events.append(("prediction_failure", tuple(options)))
        return ActivityDefinitions(("prepare",))

    def create_worker(
        self,
        client: object,
        *,
        task_queue: str,
        workflows: Sequence[type[object]],
        activities: Sequence[object],
    ) -> WorkerResource:
        self.events.append(
            (
                "worker",
                client is self.temporal,
                task_queue,
                tuple(workflow.__name__ for workflow in workflows),
                tuple(activities),
            )
        )
        return WorkerResource(self.events)

    def install_signals(self, stop_event: asyncio.Event) -> None:
        self.events.append(("signals", stop_event.is_set()))
        stop_event.set()


class EntrypointAssembly:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.events: list[tuple[object, ...]] = []

    def install(self, monkeypatch: Any, module: Any) -> None:
        settings_name = "WorkerSettings" if hasattr(module, "WorkerSettings") else "Settings"
        monkeypatch.setattr(module, settings_name, self.create_settings)
        monkeypatch.setattr(module, "configure_logging", self.configure_logging)
        monkeypatch.setattr(module, "run", self.run)

    def create_settings(self) -> Settings:
        self.events.append(("settings",))
        return self.settings

    def configure_logging(self, level: str, log_format: str, service: str) -> None:
        self.events.append(("logging", level, log_format, service))

    async def run(self, settings: Settings) -> None:
        self.events.append(("run", settings is self.settings))
