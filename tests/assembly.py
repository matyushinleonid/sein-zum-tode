import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import SecretStr

from sein_zum_tode.config import Settings


def explicit_settings() -> Settings:
    return Settings.model_construct(
        app_name="telegram-cosmos-1811",
        log_level="WARNING",
        log_format="json",
        telegram_bot_token=SecretStr("181:irregular-token"),
        telegram_polling_timeout_seconds=43,
        telegram_request_timeout_seconds=59,
        telegram_update_ttl_seconds=1823,
        conversation_ttl_seconds=1877,
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

    def install(self, monkeypatch: Any, module: Any) -> None:
        monkeypatch.setattr(module, "Bot", self.create_bot)
        monkeypatch.setattr(module, "Redis", self.create_redis)
        monkeypatch.setattr(module, "Client", SimpleNamespace(connect=self.connect_temporal))
        monkeypatch.setattr(module, "AiogramUpdateSource", self.create_source)
        monkeypatch.setattr(module, "RedisKeyValueClient", self.create_redis_client)
        monkeypatch.setattr(module, "AiogramUpdateUserResolver", self.create_resolver)
        monkeypatch.setattr(module, "RedisUpdateStore", self.create_store)
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

    def create_resolver(self) -> object:
        self.events.append(("resolver",))
        return object()

    def create_store(self, **options: object) -> object:
        self.events.append(("store", options["bot_id"], options["ttl_seconds"]))
        return object()

    def create_starter(self, **options: object) -> object:
        self.events.append(
            (
                "starter",
                options["bot_id"],
                options["task_queue"],
                options["activity_retry_timeout_seconds"],
                options["conversation_ttl_seconds"],
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


class WorkerAssembly:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.bot = BotResource(self.events)
        self.redis = RedisResource(self.events)
        self.temporal = object()
        self.payloads = object()
        self.conversations = object()
        self.sender = object()
        self.content = ContentResource()

    def install(self, monkeypatch: Any, module: Any) -> None:
        monkeypatch.setattr(module, "Bot", self.create_bot)
        monkeypatch.setattr(module, "Redis", self.create_redis)
        monkeypatch.setattr(module, "Client", SimpleNamespace(connect=self.connect_temporal))
        monkeypatch.setattr(module, "YamlBotContentLoader", self.create_content_loader)
        monkeypatch.setattr(module, "RedisTelegramPayloadRepository", self.create_payloads)
        monkeypatch.setattr(
            module,
            "RedisConversationStateRepository",
            self.create_conversations,
        )
        monkeypatch.setattr(module, "AiogramTelegramMessageSender", self.create_sender)
        monkeypatch.setattr(module, "InspectTelegramUpdateActivity", self.create_inspect)
        monkeypatch.setattr(module, "PrepareTelegramResponseActivities", self.create_prepare)
        monkeypatch.setattr(
            module,
            "StartTelegramConversationActivity",
            self.create_start_conversation,
        )
        monkeypatch.setattr(
            module,
            "RecordTelegramConversationAnswerActivity",
            self.create_record_answer,
        )
        monkeypatch.setattr(module, "DeliverTelegramResponseActivity", self.create_delivery)
        monkeypatch.setattr(module, "CleanupTelegramPayloadsActivity", self.create_cleanup)
        monkeypatch.setattr(module, "Worker", self.create_worker)
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

    def create_content_loader(self, path: Path) -> ContentLoaderResource:
        self.events.append(("content_loader", path))
        return ContentLoaderResource(self.events, self.content)

    def create_payloads(self, redis: object) -> object:
        self.events.append(("payloads", redis is self.redis))
        return self.payloads

    def create_conversations(self, redis: object) -> object:
        self.events.append(("conversations", redis is self.redis))
        return self.conversations

    def create_sender(self, bot: object) -> object:
        self.events.append(("sender", bot is self.bot))
        return self.sender

    def create_inspect(self, payloads: object) -> ActivityDefinitions:
        self.events.append(("inspect", payloads is self.payloads))
        return ActivityDefinitions(("inspect",))

    def create_prepare(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "prepare",
                options["ttl_seconds"],
                options["help_text"],
            )
        )
        return ActivityDefinitions(
            (
                "prepare_echo",
                "prepare_help",
                "prepare_unsupported",
                "prepare_group_unsupported",
            )
        )

    def create_start_conversation(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "start_conversation",
                options["content"] is self.content,
                options["conversations"] is self.conversations,
                options["responses"] is self.payloads,
                options["conversation_ttl_seconds"],
                options["response_ttl_seconds"],
                options["privacy_response_ttl_seconds"],
            )
        )
        return ActivityDefinitions(("start",))

    def create_record_answer(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "record_answer",
                options["updates"] is self.payloads,
                options["conversations"] is self.conversations,
                options["responses"] is self.payloads,
                options["conversation_ttl_seconds"],
                options["response_ttl_seconds"],
                options["privacy_response_ttl_seconds"],
            )
        )
        return ActivityDefinitions(("record",))

    def create_delivery(self, **options: object) -> ActivityDefinitions:
        self.events.append(
            (
                "delivery",
                options["response_reader"] is self.payloads,
                options["sender"] is self.sender,
            )
        )
        return ActivityDefinitions(("deliver",))

    def create_cleanup(self, **options: object) -> ActivityDefinitions:
        self.events.append(("cleanup", options["cleaner"] is self.payloads))
        return ActivityDefinitions(("cleanup",))

    def create_worker(self, client: object, **options: object) -> WorkerResource:
        self.events.append(
            (
                "worker",
                client is self.temporal,
                options["task_queue"],
                tuple(workflow.__name__ for workflow in options["workflows"]),
                tuple(options["activities"]),
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
        monkeypatch.setattr(module, "Settings", self.create_settings)
        monkeypatch.setattr(module, "configure_logging", self.configure_logging)
        monkeypatch.setattr(module, "run", self.run)

    def create_settings(self) -> Settings:
        self.events.append(("settings",))
        return self.settings

    def configure_logging(self, level: str, log_format: str, service: str) -> None:
        self.events.append(("logging", level, log_format, service))

    async def run(self, settings: Settings) -> None:
        self.events.append(("run", settings is self.settings))
