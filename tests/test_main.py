import asyncio
import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from pydantic import SecretStr

import sein_zum_tode.main as main_module
from sein_zum_tode.config import Settings


def make_settings() -> Settings:
    return Settings.model_construct(
        telegram_bot_token=SecretStr("42:token"),
        redis_password=SecretStr("redis-secret"),
    )


def test_install_signal_handlers(monkeypatch) -> None:
    loop = Mock()
    stop_event = asyncio.Event()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)

    main_module.install_signal_handlers(stop_event)

    first_call, second_call = loop.add_signal_handler.call_args_list
    assert first_call.args[0] == signal.SIGINT
    assert second_call.args[0] == signal.SIGTERM
    assert first_call.args[1] is second_call.args[1]

    first_call.args[1]()

    assert stop_event.is_set()


async def test_run_builds_ingress_and_closes_clients(monkeypatch) -> None:
    settings = make_settings()
    bot = SimpleNamespace(
        id=42,
        session=SimpleNamespace(close=AsyncMock()),
    )
    redis = SimpleNamespace(aclose=AsyncMock())
    temporal = object()
    poller = SimpleNamespace(run=AsyncMock())
    bot_factory = Mock(return_value=bot)
    redis_factory = Mock(return_value=redis)
    temporal_connect = AsyncMock(return_value=temporal)
    temporal_client = SimpleNamespace(connect=temporal_connect)
    source_factory = Mock(return_value=object())
    redis_client_factory = Mock(return_value=object())
    user_resolver_factory = Mock(return_value=object())
    store_factory = Mock(return_value=object())
    workflow_starter_factory = Mock(return_value=object())
    handoff_factory = Mock(return_value=object())
    poller_factory = Mock(return_value=poller)
    install_signal_handlers = Mock()
    monkeypatch.setattr(main_module, "Bot", bot_factory)
    monkeypatch.setattr(main_module, "Redis", redis_factory)
    monkeypatch.setattr(main_module, "Client", temporal_client)
    monkeypatch.setattr(main_module, "AiogramUpdateSource", source_factory)
    monkeypatch.setattr(main_module, "RedisKeyValueClient", redis_client_factory)
    monkeypatch.setattr(
        main_module,
        "AiogramUpdateUserResolver",
        user_resolver_factory,
    )
    monkeypatch.setattr(main_module, "RedisUpdateStore", store_factory)
    monkeypatch.setattr(
        main_module,
        "TemporalUserWorkflowStarter",
        workflow_starter_factory,
    )
    monkeypatch.setattr(main_module, "TemporalUpdateHandoff", handoff_factory)
    monkeypatch.setattr(main_module, "TelegramPoller", poller_factory)
    monkeypatch.setattr(main_module, "install_signal_handlers", install_signal_handlers)

    await main_module.run(settings)

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
    source_factory.assert_called_once_with(
        bot=bot,
        polling_timeout_seconds=30,
        request_timeout_seconds=40,
    )
    redis_client_factory.assert_called_once_with(redis)
    store_factory.assert_called_once_with(
        redis=redis_client_factory.return_value,
        user_resolver=user_resolver_factory.return_value,
        bot_id=42,
        ttl_seconds=3600,
    )
    workflow_starter_factory.assert_called_once_with(
        client=temporal,
        bot_id=42,
        task_queue="sein-zum-tode",
        activity_retry_timeout_seconds=300,
    )
    handoff_factory.assert_called_once_with(workflow_starter_factory.return_value)
    poller_factory.assert_called_once()
    retry_waiter = poller_factory.call_args.kwargs["retry_waiter"]
    assert retry_waiter.initial_delay_seconds == 1.0
    assert retry_waiter.max_delay_seconds == 30.0
    stop_event = install_signal_handlers.call_args.args[0]
    poller.run.assert_awaited_once_with(stop_event)
    bot.session.close.assert_awaited_once_with()
    redis.aclose.assert_awaited_once_with()


def test_main_loads_settings_and_runs_application(monkeypatch) -> None:
    settings = make_settings()
    configure_logging = Mock()
    captured = []

    async def run(current_settings: Settings) -> None:
        captured.append(current_settings)

    monkeypatch.setattr(main_module, "Settings", lambda: settings)
    monkeypatch.setattr(main_module, "configure_logging", configure_logging)
    monkeypatch.setattr(main_module, "run", run)

    main_module.main()

    configure_logging.assert_called_once_with(
        "INFO",
        "console",
        "sein-zum-tode-telegram-ingress",
    )
    assert captured == [settings]
