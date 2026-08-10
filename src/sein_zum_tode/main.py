import asyncio
import logging

from aiogram import Bot
from aiogram.types import Update
from temporalio.client import Client

from sein_zum_tode.config import Settings
from sein_zum_tode.infrastructure.health import (
    CallableHealthCheck,
    HealthHttpServer,
    HealthMonitor,
    HealthState,
    IngressHealth,
)
from sein_zum_tode.infrastructure.kubernetes_leases import KubernetesPollingLeaseStore
from sein_zum_tode.infrastructure.metrics import PrometheusHttpServer, PrometheusMetrics
from sein_zum_tode.infrastructure.redis import RedisClient, create_redis_transport
from sein_zum_tode.infrastructure.redis_documents import (
    PydanticJsonCodec,
    RedisJsonDocumentStore,
)
from sein_zum_tode.infrastructure.tls import create_temporal_tls_config
from sein_zum_tode.ingress.admission import WhitelistedUpdateAdmission
from sein_zum_tode.ingress.coordination import (
    LeaseCoordinatedPollingTurns,
    UncoordinatedPollingTurns,
)
from sein_zum_tode.ingress.handoff import TemporalUpdateHandoff
from sein_zum_tode.ingress.poller import ExponentialRetryWaiter, TelegramPoller
from sein_zum_tode.ingress.ports import PollingTurnCoordinator
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


def create_polling_turns(
    settings: Settings,
) -> tuple[PollingTurnCoordinator, KubernetesPollingLeaseStore | None]:
    if settings.telegram_poll_coordination_mode == "none":
        return UncoordinatedPollingTurns(), None
    leases = KubernetesPollingLeaseStore.from_service_account(
        api_url=settings.kubernetes_api_url,
        namespace=settings.telegram_poll_lease_namespace or "",
        lease_name=settings.telegram_poll_lease_name,
        token_path=settings.kubernetes_service_account_token_path,
        ca_path=settings.kubernetes_service_account_ca_path,
        request_timeout_seconds=settings.kubernetes_api_request_timeout_seconds,
    )
    return (
        LeaseCoordinatedPollingTurns(
            leases=leases,
            holder_identity=settings.telegram_poll_lease_holder_identity or "",
            lease_duration_seconds=settings.telegram_poll_lease_duration_seconds,
            retry_interval_seconds=settings.telegram_poll_lease_retry_interval_seconds,
            handoff_delay_seconds=settings.telegram_poll_lease_handoff_delay_seconds,
        ),
        leases,
    )


async def run(settings: Settings) -> None:
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    metrics, registry = PrometheusMetrics.create(component="ingress")
    health = HealthState(
        dependencies=("redis", "temporal"),
        freshness_limits={
            "telegram_polling": settings.telegram_polling_timeout_seconds * 2 + 10,
        },
        liveness_timeout_seconds=settings.health_liveness_timeout_seconds,
        success_threshold=settings.health_success_threshold,
        failure_threshold=settings.health_failure_threshold,
    )
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    redis_connection = create_redis_transport(
        host=settings.redis_host,
        port=settings.redis_port,
        database=settings.redis_database,
        username=settings.redis_username,
        password=settings.redis_password.get_secret_value(),
        socket_connect_timeout_seconds=settings.redis_socket_connect_timeout_seconds,
        socket_timeout_seconds=settings.redis_socket_timeout_seconds,
        max_connections=settings.redis_max_connections,
        health_check_interval_seconds=settings.redis_health_check_interval_seconds,
        tls=settings.redis_tls,
        tls_verify=settings.redis_tls_verify,
        tls_ca_file=settings.redis_tls_ca_file,
        tls_certificate_file=settings.redis_tls_certificate_file,
        tls_private_key_file=settings.redis_tls_private_key_file,
    )
    redis = RedisClient(redis_connection)
    polling_turns, polling_leases = create_polling_turns(settings)
    temporal = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        tls=create_temporal_tls_config(
            enabled=settings.temporal_tls,
            server_name=settings.temporal_tls_server_name,
            ca_file=settings.temporal_tls_ca_file,
            certificate_file=settings.temporal_tls_certificate_file,
            private_key_file=settings.temporal_tls_private_key_file,
        ),
    )
    source = AiogramUpdateSource(
        bot=bot,
        polling_timeout_seconds=settings.telegram_polling_timeout_seconds,
        request_timeout_seconds=settings.telegram_request_timeout_seconds,
    )
    user_resolver = AiogramUpdateUserResolver()
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
        user_resolver=user_resolver,
        bot_id=bot.id,
        ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    workflow_starter = TemporalUserWorkflowStarter(
        client=TemporalClientAdapter(temporal),
        bot_id=bot.id,
        task_queue=settings.temporal_task_queue,
        activity_retry_timeout_seconds=settings.temporal_activity_retry_timeout_seconds,
        questionnaire_ttl_seconds=settings.questionnaire_ttl_seconds,
        broadcast_recipient_page_size=settings.broadcast_recipient_page_size,
    )
    poller = TelegramPoller(
        source=source,
        store=store,
        admission=WhitelistedUpdateAdmission(
            user_resolver=user_resolver,
            allowed_user_ids=settings.telegram_allowed_user_ids,
            metrics=metrics,
        ),
        handoff=TemporalUpdateHandoff(
            workflow_starter=workflow_starter,
            metrics=metrics,
        ),
        retry_waiter=ExponentialRetryWaiter(
            initial_delay_seconds=settings.retry_initial_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
        ),
        metrics=metrics,
        health=IngressHealth(health),
        polling_turns=polling_turns,
    )
    health_monitor = HealthMonitor(
        state=health,
        checks=(
            CallableHealthCheck(name="redis", probe=redis.ping),
            CallableHealthCheck(
                name="temporal",
                probe=temporal.service_client.check_health,
            ),
        ),
        interval_seconds=settings.health_check_interval_seconds,
        timeout_seconds=settings.health_check_timeout_seconds,
        metrics=metrics,
    )
    metrics_server = PrometheusHttpServer.start(
        host=settings.metrics_host,
        port=settings.metrics_port,
        registry=registry,
    )
    health_server = HealthHttpServer.start(
        host=settings.health_host,
        port=settings.health_port,
        state=health,
    )
    health_task = asyncio.create_task(health_monitor.run(stop_event))
    logging.getLogger(__name__).info(
        "Telegram ingress started",
        extra=LogContext(component="ingress").event("application_started"),
    )
    try:
        await poller.run(stop_event)
    finally:
        health.stopping()
        stop_event.set()
        await health_task
        logging.getLogger(__name__).info(
            "Telegram ingress stopping",
            extra=LogContext(component="ingress").event("application_stopping"),
        )
        health_server.close()
        metrics_server.close()
        await bot.session.close()
        if polling_leases is not None:
            await polling_leases.close()
        await redis_connection.aclose()


def main() -> None:
    settings = Settings.from_environment()
    configure_logging(settings.log_level, settings.log_format, settings.app_name)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
