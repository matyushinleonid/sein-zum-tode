import asyncio
import logging

from aiogram import Bot
from aiogram.types import Update
from redis.asyncio import Redis
from temporalio.client import Client

from sein_zum_tode.config import Settings
from sein_zum_tode.infrastructure.metrics import PrometheusHttpServer, PrometheusMetrics
from sein_zum_tode.infrastructure.redis import RedisClient
from sein_zum_tode.infrastructure.redis_documents import (
    PydanticJsonCodec,
    RedisJsonDocumentStore,
)
from sein_zum_tode.ingress.handoff import TemporalUpdateHandoff
from sein_zum_tode.ingress.poller import ExponentialRetryWaiter, TelegramPoller
from sein_zum_tode.ingress.routing import AiogramUpdateUserResolver
from sein_zum_tode.ingress.source import AiogramUpdateSource
from sein_zum_tode.ingress.store import TelegramUpdateStore
from sein_zum_tode.ingress.temporal import (
    TemporalClientAdapter,
    TemporalUserWorkflowStarter,
)
from sein_zum_tode.log_config import configure_logging
from sein_zum_tode.observability import LogContext
from sein_zum_tode.runtime import install_signal_handlers


async def run(settings: Settings) -> None:
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    metrics, registry = PrometheusMetrics.create(component="ingress")
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    redis_connection = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_database,
        password=settings.redis_password.get_secret_value(),
    )
    redis = RedisClient(redis_connection)
    temporal = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        tls=settings.temporal_tls,
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=settings.telegram_polling_timeout_seconds,
        request_timeout_seconds=settings.telegram_request_timeout_seconds,
    )
    store = TelegramUpdateStore(
        updates=RedisJsonDocumentStore(
            redis=redis,
            codec=PydanticJsonCodec(
                model=Update,
                by_alias=True,
                exclude_none=True,
            ),
            document_name="Telegram update",
        ),
        user_resolver=AiogramUpdateUserResolver(),
        bot_id=bot.id,
        ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    workflow_starter = TemporalUserWorkflowStarter(
        client=TemporalClientAdapter(temporal),
        bot_id=bot.id,
        task_queue=settings.temporal_task_queue,
        activity_retry_timeout_seconds=settings.temporal_activity_retry_timeout_seconds,
        questionnaire_ttl_seconds=settings.questionnaire_ttl_seconds,
    )
    poller = TelegramPoller(
        source=source,
        store=store,
        handoff=TemporalUpdateHandoff(workflow_starter, metrics=metrics),
        retry_waiter=ExponentialRetryWaiter(
            initial_delay_seconds=settings.retry_initial_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
        ),
        metrics=metrics,
    )
    metrics_server = PrometheusHttpServer.start(
        host=settings.metrics_host,
        port=settings.metrics_port,
        registry=registry,
    )
    logging.getLogger(__name__).info(
        "Telegram ingress started",
        extra=LogContext(component="ingress").event("application_started"),
    )
    try:
        await poller.run(stop_event)
    finally:
        logging.getLogger(__name__).info(
            "Telegram ingress stopping",
            extra=LogContext(component="ingress").event("application_stopping"),
        )
        metrics_server.close()
        await bot.session.close()
        await redis_connection.aclose()


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, settings.app_name)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
