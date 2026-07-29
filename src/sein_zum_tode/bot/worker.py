import asyncio

from aiogram import Bot
from redis.asyncio import Redis
from temporalio.client import Client
from temporalio.worker import Worker

from sein_zum_tode.bot.activities import (
    CleanupTelegramPayloadsActivity,
    DeliverTelegramResponseActivity,
    InspectTelegramUpdateActivity,
    PrepareTelegramResponseActivities,
)
from sein_zum_tode.bot.redis import RedisTelegramPayloadRepository
from sein_zum_tode.bot.sender import AiogramTelegramMessageSender
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.config import Settings
from sein_zum_tode.log_config import configure_logging
from sein_zum_tode.runtime import install_signal_handlers


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
    temporal = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls,
    )
    payloads = RedisTelegramPayloadRepository(redis)
    sender = AiogramTelegramMessageSender(bot)
    inspect = InspectTelegramUpdateActivity(payloads)
    prepare = PrepareTelegramResponseActivities(
        update_reader=payloads,
        response_store=payloads,
        ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    deliver = DeliverTelegramResponseActivity(payloads, sender)
    cleanup = CleanupTelegramPayloadsActivity(payloads)
    worker = Worker(
        temporal,
        task_queue=settings.temporal_task_queue,
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
    try:
        async with worker:
            await stop_event.wait()
    finally:
        await bot.session.close()
        await redis.aclose()


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_name)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
