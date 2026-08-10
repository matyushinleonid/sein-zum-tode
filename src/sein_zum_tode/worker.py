import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.types import Update
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from temporalio.client import Client
from temporalio.worker import Worker
from yandex_ai_studio_sdk import AsyncAIStudio

from sein_zum_tode.bot.activities import (
    CleanupTelegramPayloadsActivity,
    DeliverTelegramResponseActivity,
    InspectTelegramUpdateActivity,
    PrepareTelegramResponseActivities,
)
from sein_zum_tode.bot.content import BotContent, YamlBotContentLoader
from sein_zum_tode.bot.keyboards import TelegramKeyboardCatalog
from sein_zum_tode.bot.models import TelegramResponse
from sein_zum_tode.bot.sender import AiogramTelegramMessageSender
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.broadcasts.activities import (
    DeliverScreamActivity,
    ListScreamRecipientsActivity,
    PrepareScreamReportActivity,
)
from sein_zum_tode.broadcasts.workflow import TelegramScreamWorkflow
from sein_zum_tode.config import WorkerSettings
from sein_zum_tode.infrastructure.completion_config import CompletionProvider
from sein_zum_tode.infrastructure.cron_descriptor import CronDescriptor
from sein_zum_tode.infrastructure.health import (
    CallableHealthCheck,
    HealthHttpServer,
    HealthMonitor,
    HealthState,
)
from sein_zum_tode.infrastructure.metrics import PrometheusHttpServer, PrometheusMetrics
from sein_zum_tode.infrastructure.numbers import Num2WordsNumberSpeller
from sein_zum_tode.infrastructure.openai import (
    AsyncOpenAISdkAdapter,
    OpenAICompletionClient,
    OpenAICompletionProfile,
    Socks5Proxy,
)
from sein_zum_tode.infrastructure.postgres import PostgresClient
from sein_zum_tode.infrastructure.redis import RedisClient, create_redis_transport
from sein_zum_tode.infrastructure.redis_documents import (
    PydanticJsonCodec,
    RedisJsonDocumentStore,
    RedisKeyCleaner,
)
from sein_zum_tode.infrastructure.tls import create_temporal_tls_config
from sein_zum_tode.infrastructure.yandex_ai import (
    YandexAIStudioClient,
    YandexCompletionProfile,
)
from sein_zum_tode.localization.settings import ConfigureMortalLocalizationActivity
from sein_zum_tode.log_config import configure_logging
from sein_zum_tode.mortals.activities import MortalActivities
from sein_zum_tode.mortals.models import MortalRegistrationDefaults
from sein_zum_tode.mortals.postgres import PostgresMortalRepository
from sein_zum_tode.notifications.activities import (
    PrepareMortalNotificationActivity,
    PrepareNotificationSampleActivity,
)
from sein_zum_tode.notifications.custom_schedule.activities import (
    ApplyCustomNotificationScheduleActivity,
    GenerateCustomNotificationScheduleActivity,
    PrepareCustomNotificationFailureActivity,
)
from sein_zum_tode.notifications.custom_schedule.config import (
    NotificationScheduleConfig,
    NotificationScheduleConfigurationError,
    YamlNotificationScheduleConfigLoader,
)
from sein_zum_tode.notifications.custom_schedule.llm import (
    LLMNotificationScheduleInterpreter,
)
from sein_zum_tode.notifications.custom_schedule.mock import (
    MockNotificationScheduleInterpreter,
)
from sein_zum_tode.notifications.custom_schedule.models import (
    NotificationScheduleProposal,
    StoredNotificationScheduleProposal,
)
from sein_zum_tode.notifications.custom_schedule.ports import (
    NotificationScheduleInterpreter,
)
from sein_zum_tode.notifications.custom_schedule.presentation import (
    NotificationSchedulePresenter,
)
from sein_zum_tode.notifications.custom_schedule.validation import (
    NotificationScheduleValidator,
)
from sein_zum_tode.notifications.presentation import NotificationMessagePresenter
from sein_zum_tode.notifications.settings import ConfigureMortalNotificationsActivity
from sein_zum_tode.notifications.temporal import TemporalMortalSchedule
from sein_zum_tode.notifications.workflow import MortalNotificationWorkflow
from sein_zum_tode.observability import LogContext
from sein_zum_tode.prediction.activities import (
    ApplyDeathPredictionActivity,
    GenerateDeathPredictionActivity,
    PreparePredictionFailureActivity,
)
from sein_zum_tode.prediction.config import (
    DeathPredictionConfig,
    PredictionConfigurationError,
    YamlDeathPredictionConfigLoader,
)
from sein_zum_tode.prediction.llm import LLMDeathPredictor
from sein_zum_tode.prediction.mock import MockDeathPredictor
from sein_zum_tode.prediction.models import DeathPrediction, StoredDeathPrediction
from sein_zum_tode.prediction.ports import DeathPredictor
from sein_zum_tode.questionnaire.activities import (
    RecordTelegramQuestionnaireAnswerActivity,
    StartTelegramQuestionnaireActivity,
)
from sein_zum_tode.questionnaire.models import QuestionnaireState
from sein_zum_tode.questionnaire.workflow import TelegramQuestionnaireWorkflow
from sein_zum_tode.runtime import install_signal_handlers
from sein_zum_tode.unsupported.activities import PrepareUnsupportedResponseActivity
from sein_zum_tode.unsupported.models import UnsupportedUpdateSession


def create_death_predictor(
    *,
    config: DeathPredictionConfig,
    content: BotContent,
    settings: WorkerSettings,
    provider: CompletionProvider | None = None,
) -> DeathPredictor:
    selected = provider if provider is not None else config.provider
    if selected == CompletionProvider.MOCK:
        return MockDeathPredictor(
            config=config.mock,
            content=content,
        )
    if selected == CompletionProvider.OPENAI:
        if (
            settings.openai_api_key is None
            or not settings.openai_api_key.get_secret_value()
            or not settings.socks5_proxy_host
            or settings.socks5_proxy_port is None
            or not settings.socks5_proxy_username
            or settings.socks5_proxy_password is None
            or not settings.socks5_proxy_password.get_secret_value()
        ):
            raise PredictionConfigurationError(
                "OPENAI_API_KEY and complete SOCKS5 proxy settings are required"
            )
        proxy = Socks5Proxy(
            host=settings.socks5_proxy_host,
            port=settings.socks5_proxy_port,
            username=settings.socks5_proxy_username,
            password=settings.socks5_proxy_password.get_secret_value(),
        )
        openai_sdk = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            http_client=DefaultAsyncHttpxClient(proxy=proxy.url()),
        )
        openai_adapter: AsyncOpenAISdkAdapter[DeathPrediction] = AsyncOpenAISdkAdapter(openai_sdk)
        return LLMDeathPredictor(
            client=OpenAICompletionClient(
                sdk=openai_adapter,
                profile=OpenAICompletionProfile(
                    model=config.openai.model,
                    reasoning_effort=config.openai.reasoning_effort,
                    max_output_tokens=config.openai.max_output_tokens,
                    request_timeout_seconds=config.openai.request_timeout_seconds,
                    system_prompt=config.system_prompt,
                ),
                response_type=DeathPrediction,
            )
        )
    if (
        settings.yandex_ai_studio_api_key is None
        or not settings.yandex_ai_studio_api_key.get_secret_value()
        or not settings.yandex_ai_studio_folder_id
    ):
        raise PredictionConfigurationError(
            "YANDEX_AI_STUDIO_API_KEY and YANDEX_AI_STUDIO_FOLDER_ID are required"
        )
    yandex_sdk = AsyncAIStudio(
        folder_id=settings.yandex_ai_studio_folder_id,
        auth=settings.yandex_ai_studio_api_key.get_secret_value(),
        enable_server_data_logging=settings.yandex_ai_studio_enable_server_data_logging,
    )
    return LLMDeathPredictor(
        client=YandexAIStudioClient(
            sdk=yandex_sdk,
            profile=YandexCompletionProfile(
                model=config.yandex.model,
                model_version=config.yandex.model_version,
                temperature=config.yandex.temperature,
                max_tokens=config.yandex.max_tokens,
                request_timeout_seconds=config.yandex.request_timeout_seconds,
                system_prompt=config.system_prompt,
            ),
            response_type=DeathPrediction,
        )
    )


def create_notification_schedule_interpreter(
    *,
    config: NotificationScheduleConfig,
    content: BotContent,
    settings: WorkerSettings,
    provider: CompletionProvider | None = None,
) -> NotificationScheduleInterpreter:
    selected = provider if provider is not None else config.provider
    if selected == CompletionProvider.MOCK:
        return MockNotificationScheduleInterpreter(
            config=config.mock,
            content=content,
        )
    if selected == CompletionProvider.OPENAI:
        if (
            settings.openai_api_key is None
            or not settings.openai_api_key.get_secret_value()
            or not settings.socks5_proxy_host
            or settings.socks5_proxy_port is None
            or not settings.socks5_proxy_username
            or settings.socks5_proxy_password is None
            or not settings.socks5_proxy_password.get_secret_value()
        ):
            raise NotificationScheduleConfigurationError(
                "OPENAI_API_KEY and complete SOCKS5 proxy settings are required"
            )
        proxy = Socks5Proxy(
            host=settings.socks5_proxy_host,
            port=settings.socks5_proxy_port,
            username=settings.socks5_proxy_username,
            password=settings.socks5_proxy_password.get_secret_value(),
        )
        openai_sdk = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            http_client=DefaultAsyncHttpxClient(proxy=proxy.url()),
        )
        openai_adapter: AsyncOpenAISdkAdapter[NotificationScheduleProposal] = AsyncOpenAISdkAdapter(
            openai_sdk
        )
        return LLMNotificationScheduleInterpreter(
            client=OpenAICompletionClient(
                sdk=openai_adapter,
                profile=OpenAICompletionProfile(
                    model=config.openai.model,
                    reasoning_effort=config.openai.reasoning_effort,
                    max_output_tokens=config.openai.max_output_tokens,
                    request_timeout_seconds=config.openai.request_timeout_seconds,
                    system_prompt=config.system_prompt,
                ),
                response_type=NotificationScheduleProposal,
            )
        )
    if (
        settings.yandex_ai_studio_api_key is None
        or not settings.yandex_ai_studio_api_key.get_secret_value()
        or not settings.yandex_ai_studio_folder_id
    ):
        raise NotificationScheduleConfigurationError(
            "YANDEX_AI_STUDIO_API_KEY and YANDEX_AI_STUDIO_FOLDER_ID are required"
        )
    yandex_sdk = AsyncAIStudio(
        folder_id=settings.yandex_ai_studio_folder_id,
        auth=settings.yandex_ai_studio_api_key.get_secret_value(),
        enable_server_data_logging=settings.yandex_ai_studio_enable_server_data_logging,
    )
    return LLMNotificationScheduleInterpreter(
        client=YandexAIStudioClient(
            sdk=yandex_sdk,
            profile=YandexCompletionProfile(
                model=config.yandex.model,
                model_version=config.yandex.model_version,
                temperature=config.yandex.temperature,
                max_tokens=config.yandex.max_tokens,
                request_timeout_seconds=config.yandex.request_timeout_seconds,
                system_prompt=config.system_prompt,
            ),
            response_type=NotificationScheduleProposal,
        )
    )


async def run(settings: WorkerSettings) -> None:
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    metrics, registry = PrometheusMetrics.create(component="worker")
    health = HealthState(
        dependencies=("postgres", "redis", "temporal"),
        liveness_timeout_seconds=settings.health_liveness_timeout_seconds,
        success_threshold=settings.health_success_threshold,
        failure_threshold=settings.health_failure_threshold,
    )
    content = YamlBotContentLoader(settings.bot_content_path).load()
    prediction_config = YamlDeathPredictionConfigLoader(
        settings.death_prediction_config_path
    ).load()
    notification_schedule_config = YamlNotificationScheduleConfigLoader(
        settings.notification_schedule_config_path
    ).load()
    keyboards = TelegramKeyboardCatalog(
        content=content,
        notification_presets=notification_schedule_config.presets,
        mode=settings.telegram_keyboard_mode,
    )
    predictor = create_death_predictor(
        config=prediction_config,
        content=content,
        settings=settings,
    )
    fallback_predictor = (
        None
        if prediction_config.fallback_provider is None
        else create_death_predictor(
            config=prediction_config,
            content=content,
            settings=settings,
            provider=prediction_config.fallback_provider,
        )
    )
    schedule_interpreter = create_notification_schedule_interpreter(
        config=notification_schedule_config,
        content=content,
        settings=settings,
    )
    fallback_schedule_interpreter = (
        None
        if notification_schedule_config.fallback_provider is None
        else create_notification_schedule_interpreter(
            config=notification_schedule_config,
            content=content,
            settings=settings,
            provider=notification_schedule_config.fallback_provider,
        )
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
    update_documents = RedisJsonDocumentStore(
        redis=redis,
        codec=PydanticJsonCodec(model=Update),
        document_name="Telegram update",
    )
    response_documents = RedisJsonDocumentStore(
        redis=redis,
        codec=PydanticJsonCodec(model=TelegramResponse),
        document_name="Telegram response",
    )
    questionnaires = RedisJsonDocumentStore(
        redis=redis,
        codec=PydanticJsonCodec(model=QuestionnaireState),
        document_name="Telegram questionnaire",
    )
    predictions = RedisJsonDocumentStore(
        redis=redis,
        codec=PydanticJsonCodec(model=StoredDeathPrediction),
        document_name="death prediction",
    )
    notification_schedule_proposals = RedisJsonDocumentStore(
        redis=redis,
        codec=PydanticJsonCodec(model=StoredNotificationScheduleProposal),
        document_name="notification schedule proposal",
    )
    unsupported_update_sessions = RedisJsonDocumentStore(
        redis=redis,
        codec=PydanticJsonCodec(model=UnsupportedUpdateSession),
        document_name="unsupported Telegram update session",
    )
    cleaner = RedisKeyCleaner(redis)
    postgres = PostgresClient.create(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_database,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        tls_mode=settings.postgres_tls_mode,
        tls_ca_file=settings.postgres_tls_ca_file,
        tls_certificate_file=settings.postgres_tls_certificate_file,
        tls_private_key_file=settings.postgres_tls_private_key_file,
        pgbouncer=settings.postgres_pgbouncer,
        connect_timeout_seconds=settings.postgres_connect_timeout_seconds,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
        pool_timeout_seconds=settings.postgres_pool_timeout_seconds,
        pool_recycle_seconds=settings.postgres_pool_recycle_seconds,
    )
    mortals = PostgresMortalRepository(
        postgres,
        registration_defaults=MortalRegistrationDefaults(
            timezone=notification_schedule_config.default_timezone,
            notification_cron=notification_schedule_config.default_cron(),
        ),
    )
    schedules = TemporalMortalSchedule(
        client=temporal,
        bot_id=bot.id,
        task_queue=settings.temporal_task_queue,
        activity_retry_timeout_seconds=settings.temporal_activity_retry_timeout_seconds,
    )
    sender = AiogramTelegramMessageSender(bot)
    inspect = InspectTelegramUpdateActivity(
        update_reader=update_documents,
        keyboards=keyboards,
        admin_user_ids=settings.telegram_admin_user_ids,
        metrics=metrics,
    )
    prepare = PrepareTelegramResponseActivities(
        response_store=response_documents,
        ttl_seconds=settings.telegram_update_ttl_seconds,
        content=content,
        mortals=mortals,
        keyboards=keyboards,
        metrics=metrics,
    )
    prepare_unsupported = PrepareUnsupportedResponseActivity(
        sessions=unsupported_update_sessions,
        responses=response_documents,
        content=content.unsupported_updates,
        bot_content=content,
        mortals=mortals,
        bot_id=bot.id,
        session_ttl_seconds=settings.unsupported_update_session_ttl_seconds,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    start_questionnaire = StartTelegramQuestionnaireActivity(
        content=content,
        mortals=mortals,
        questionnaires=questionnaires,
        responses=response_documents,
        questionnaire_ttl_seconds=settings.questionnaire_ttl_seconds,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        privacy_response_ttl_seconds=(
            settings.questionnaire_ttl_seconds + settings.temporal_activity_retry_timeout_seconds
        ),
        metrics=metrics,
    )
    record_answer = RecordTelegramQuestionnaireAnswerActivity(
        updates=update_documents,
        questionnaires=questionnaires,
        responses=response_documents,
        questionnaire_ttl_seconds=settings.questionnaire_ttl_seconds,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        privacy_response_ttl_seconds=(
            settings.questionnaire_ttl_seconds + settings.temporal_activity_retry_timeout_seconds
        ),
        metrics=metrics,
    )
    deliver = DeliverTelegramResponseActivity(
        response_reader=response_documents,
        sender=sender,
        metrics=metrics,
    )
    cleanup = CleanupTelegramPayloadsActivity(cleaner=cleaner, metrics=metrics)
    list_scream_recipients = ListScreamRecipientsActivity(mortals=mortals)
    deliver_scream = DeliverScreamActivity(copier=sender, metrics=metrics)
    prepare_scream_report = PrepareScreamReportActivity(
        responses=response_documents,
        ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    mortal_activities = MortalActivities(
        mortals=mortals,
        schedules=schedules,
        metrics=metrics,
    )
    configure_notifications = ConfigureMortalNotificationsActivity(
        updates=update_documents,
        responses=response_documents,
        mortals=mortals,
        schedules=schedules,
        content=content,
        presets=notification_schedule_config.presets,
        keyboards=keyboards,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        metrics=metrics,
    )
    generate_notification_schedule = GenerateCustomNotificationScheduleActivity(
        interpreter=schedule_interpreter,
        proposals=notification_schedule_proposals,
        updates=update_documents,
        mortals=mortals,
        default_locale=content.default_locale,
        ttl_seconds=settings.telegram_update_ttl_seconds,
        fallback_interpreter=fallback_schedule_interpreter,
        metrics=metrics,
    )
    apply_notification_schedule = ApplyCustomNotificationScheduleActivity(
        proposals=notification_schedule_proposals,
        responses=response_documents,
        mortals=mortals,
        schedules=schedules,
        validator=NotificationScheduleValidator(
            minimum_interval=timedelta(hours=notification_schedule_config.minimum_interval_hours)
        ),
        presenter=NotificationSchedulePresenter(descriptions=CronDescriptor()),
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        metrics=metrics,
    )
    prepare_notification_schedule_failure = PrepareCustomNotificationFailureActivity(
        mortals=mortals,
        responses=response_documents,
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    configure_localization = ConfigureMortalLocalizationActivity(
        updates=update_documents,
        responses=response_documents,
        mortals=mortals,
        content=content,
        keyboards=keyboards,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    generate_prediction = GenerateDeathPredictionActivity(
        predictor=predictor,
        predictions=predictions,
        questionnaires=questionnaires,
        mortals=mortals,
        ttl_seconds=settings.questionnaire_ttl_seconds,
        fallback_predictor=fallback_predictor,
        metrics=metrics,
    )
    apply_prediction = ApplyDeathPredictionActivity(
        predictions=predictions,
        mortals=mortals,
        schedules=schedules,
        responses=response_documents,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        metrics=metrics,
    )
    prepare_prediction_failure = PreparePredictionFailureActivity(
        mortals=mortals,
        responses=response_documents,
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    notification_presenter = NotificationMessagePresenter(
        content=content,
        number_speller=Num2WordsNumberSpeller.create(),
    )
    prepare_notification = PrepareMortalNotificationActivity(
        mortals=mortals,
        responses=response_documents,
        presenter=notification_presenter,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        metrics=metrics,
    )
    prepare_notification_sample = PrepareNotificationSampleActivity(
        mortals=mortals,
        responses=response_documents,
        presenter=notification_presenter,
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        metrics=metrics,
    )
    worker = Worker(
        temporal,
        task_queue=settings.temporal_task_queue,
        workflows=[
            TelegramUserWorkflow,
            TelegramQuestionnaireWorkflow,
            MortalNotificationWorkflow,
            TelegramScreamWorkflow,
        ],
        activities=[
            inspect.inspect,
            prepare.prepare_help,
            prepare.prepare_about,
            prepare.prepare_localization,
            prepare.prepare_notifications,
            prepare.prepare_custom_notification,
            prepare.prepare_limit_exhausted,
            prepare.prepare_payload_expired,
            prepare_unsupported.prepare_unsupported,
            prepare.prepare_group_unsupported,
            prepare.prepare_scream_denied,
            start_questionnaire.start,
            record_answer.record,
            deliver.deliver,
            cleanup.cleanup,
            list_scream_recipients.list,
            deliver_scream.deliver,
            prepare_scream_report.prepare,
            mortal_activities.ensure,
            mortal_activities.has_quota,
            mortal_activities.mark_unreachable,
            mortal_activities.delete_schedule,
            prepare_notification.prepare,
            prepare_notification_sample.prepare,
            configure_localization.configure,
            configure_notifications.configure,
            generate_notification_schedule.generate,
            apply_notification_schedule.apply,
            prepare_notification_schedule_failure.prepare,
            generate_prediction.generate,
            apply_prediction.apply,
            prepare_prediction_failure.prepare,
        ],
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
    health_monitor = HealthMonitor(
        state=health,
        checks=(
            CallableHealthCheck(name="postgres", probe=postgres.ping),
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
    health_task = asyncio.create_task(health_monitor.run(stop_event))
    logging.getLogger(__name__).info(
        "Telegram worker started",
        extra=LogContext(component="worker").event("application_started"),
    )
    try:
        async with worker:
            health.startup_completed()
            await stop_event.wait()
    finally:
        health.stopping()
        stop_event.set()
        await health_task
        logging.getLogger(__name__).info(
            "Telegram worker stopping",
            extra=LogContext(component="worker").event("application_stopping"),
        )
        health_server.close()
        metrics_server.close()
        await predictor.close()
        if fallback_predictor is not None:
            await fallback_predictor.close()
        await schedule_interpreter.close()
        if fallback_schedule_interpreter is not None:
            await fallback_schedule_interpreter.close()
        await bot.session.close()
        await redis_connection.aclose()
        await postgres.close()


def main() -> None:
    settings = WorkerSettings.from_environment()
    configure_logging(settings.log_level, settings.log_format, settings.app_name)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
