import asyncio
import signal

from aiogram import Bot
from redis.asyncio import Redis

from sein_zum_tode.config import Settings
from sein_zum_tode.ingress.handoff import LoggingUpdateHandoff
from sein_zum_tode.ingress.poller import ExponentialRetryWaiter, TelegramPoller
from sein_zum_tode.ingress.redis import RedisKeyValueClient
from sein_zum_tode.ingress.source import AiogramUpdateSource
from sein_zum_tode.ingress.store import RedisUpdateStore
from sein_zum_tode.log_config import configure_logging


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)


async def run(settings: Settings) -> None:
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    redis = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_database,
        password=settings.redis_password.get_secret_value(),
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=settings.telegram_polling_timeout_seconds,
        request_timeout_seconds=settings.telegram_request_timeout_seconds,
    )
    store = RedisUpdateStore(
        redis=RedisKeyValueClient(redis),
        bot_id=bot.id,
        ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    poller = TelegramPoller(
        source=source,
        store=store,
        handoff=LoggingUpdateHandoff(),
        retry_waiter=ExponentialRetryWaiter(
            initial_delay_seconds=settings.retry_initial_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
        ),
    )
    try:
        await poller.run(stop_event)
    finally:
        await bot.session.close()
        await redis.aclose()


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
