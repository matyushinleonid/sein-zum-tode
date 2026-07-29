from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

from pydantic import SecretStr

import sein_zum_tode.bot.worker as worker_module
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.config import Settings


def make_settings() -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr("42:token"),
        redis_password=SecretStr("redis-secret"),
    )


async def test_run_builds_worker_and_closes_clients(monkeypatch) -> None:
    settings = make_settings()
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    redis = SimpleNamespace(aclose=AsyncMock())
    temporal = object()
    payloads = object()
    sender = object()
    inspect = SimpleNamespace(inspect=object())
    prepare = SimpleNamespace(
        prepare_echo=object(),
        prepare_help=object(),
        prepare_unsupported=object(),
        prepare_group_unsupported=object(),
    )
    deliver = SimpleNamespace(deliver=object())
    cleanup = SimpleNamespace(cleanup=object())
    worker = MagicMock()
    worker.__aenter__ = AsyncMock(return_value=worker)
    worker.__aexit__ = AsyncMock(return_value=None)

    bot_factory = Mock(return_value=bot)
    redis_factory = Mock(return_value=redis)
    temporal_connect = AsyncMock(return_value=temporal)
    temporal_client = SimpleNamespace(connect=temporal_connect)
    payloads_factory = Mock(return_value=payloads)
    sender_factory = Mock(return_value=sender)
    inspect_factory = Mock(return_value=inspect)
    prepare_factory = Mock(return_value=prepare)
    deliver_factory = Mock(return_value=deliver)
    cleanup_factory = Mock(return_value=cleanup)
    worker_factory = Mock(return_value=worker)
    install_signal_handlers = Mock(side_effect=lambda event: event.set())

    monkeypatch.setattr(worker_module, "Bot", bot_factory)
    monkeypatch.setattr(worker_module, "Redis", redis_factory)
    monkeypatch.setattr(worker_module, "Client", temporal_client)
    monkeypatch.setattr(
        worker_module,
        "RedisTelegramPayloadRepository",
        payloads_factory,
    )
    monkeypatch.setattr(
        worker_module,
        "AiogramTelegramMessageSender",
        sender_factory,
    )
    monkeypatch.setattr(
        worker_module,
        "InspectTelegramUpdateActivity",
        inspect_factory,
    )
    monkeypatch.setattr(
        worker_module,
        "PrepareTelegramResponseActivities",
        prepare_factory,
    )
    monkeypatch.setattr(
        worker_module,
        "DeliverTelegramResponseActivity",
        deliver_factory,
    )
    monkeypatch.setattr(
        worker_module,
        "CleanupTelegramPayloadsActivity",
        cleanup_factory,
    )
    monkeypatch.setattr(worker_module, "Worker", worker_factory)
    monkeypatch.setattr(
        worker_module,
        "install_signal_handlers",
        install_signal_handlers,
    )

    await worker_module.run(settings)

    bot_factory.assert_called_once_with(token="42:token")
    redis_factory.assert_called_once_with(
        host="localhost",
        port=6379,
        db=0,
        password="redis-secret",
    )
    temporal_connect.assert_awaited_once_with(
        "localhost:7233",
        namespace="default",
        tls=False,
    )
    payloads_factory.assert_called_once_with(redis)
    sender_factory.assert_called_once_with(bot)
    inspect_factory.assert_called_once_with(payloads)
    prepare_factory.assert_called_once_with(
        update_reader=payloads,
        response_store=payloads,
        ttl_seconds=3600,
    )
    deliver_factory.assert_called_once_with(payloads, sender)
    cleanup_factory.assert_called_once_with(payloads)
    worker_factory.assert_called_once_with(
        temporal,
        task_queue="sein-zum-tode",
        workflows=[TelegramUserWorkflow],
        activities=[
            inspect.inspect,
            prepare.prepare_echo,
            prepare.prepare_help,
            prepare.prepare_unsupported,
            prepare.prepare_group_unsupported,
            deliver.deliver,
            cleanup.cleanup,
        ],
    )
    install_signal_handlers.assert_called_once()
    worker.__aenter__.assert_awaited_once_with()
    worker.__aexit__.assert_awaited_once()
    bot.session.close.assert_awaited_once_with()
    redis.aclose.assert_awaited_once_with()


def test_main_loads_settings_and_runs_worker(monkeypatch) -> None:
    settings = make_settings()
    configure_logging = Mock()
    captured = []

    async def run(current_settings: Settings) -> None:
        captured.append(current_settings)

    monkeypatch.setattr(worker_module, "Settings", lambda: settings)
    monkeypatch.setattr(worker_module, "configure_logging", configure_logging)
    monkeypatch.setattr(worker_module, "run", run)

    worker_module.main()

    configure_logging.assert_called_once_with(
        "INFO",
        "console",
        "sein-zum-tode-telegram-ingress",
    )
    assert captured == [settings]
