import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.types import Update
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from redis.asyncio import Redis
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
from sein_zum_tode.infrastructure.metrics import PrometheusHttpServer, PrometheusMetrics
from sein_zum_tode.infrastructure.numbers import Num2WordsNumberSpeller
from sein_zum_tode.infrastructure.openai import (
    AsyncOpenAISdkAdapter,
    OpenAICompletionClient,
    OpenAICompletionProfile,
    Socks5Proxy,
)
from sein_zum_tode.infrastructure.postgres import PostgresClient
from sein_zum_tode.infrastructure.redis import RedisClient
from sein_zum_tode.infrastructure.redis_documents import (
    PydanticJsonCodec,
    RedisJsonDocumentStore,
    RedisKeyCleaner,
)
from sein_zum_tode.infrastructure.yandex_ai import (
    YandexAIStudioClient,
    YandexCompletionProfile,
)
from sein_zum_tode.localization.settings import ConfigureMortalLocalizationActivity
from sein_zum_tode.log_config import configure_logging
from sein_zum_tode.mortals.activities import MortalActivities
from sein_zum_tode.mortals.models import MortalRegistrationDefaults
from sein_zum_tode.mortals.postgres import PostgresMortalRepository
from sein_zum_tode.notifications.activities import PrepareMortalNotificationActivity
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
) -> DeathPredictor:
    if config.provider == CompletionProvider.MOCK:
        return MockDeathPredictor(
            config=config.mock,
            content=content,
        )
    if config.provider == CompletionProvider.OPENAI:
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
        return LLMDeathPredictor(
            client=OpenAICompletionClient(
                sdk=AsyncOpenAISdkAdapter(openai_sdk),
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
) -> NotificationScheduleInterpreter:
    if config.provider == CompletionProvider.MOCK:
        return MockNotificationScheduleInterpreter(
            config=config.mock,
            content=content,
        )
    if config.provider == CompletionProvider.OPENAI:
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
        return LLMNotificationScheduleInterpreter(
            client=OpenAICompletionClient(
                sdk=AsyncOpenAISdkAdapter(openai_sdk),
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
    content = YamlBotContentLoader(settings.bot_content_path).load()
    prediction_config = YamlDeathPredictionConfigLoader(
        settings.death_prediction_config_path
    ).load()
    notification_schedule_config = YamlNotificationScheduleConfigLoader(
        settings.notification_schedule_config_path
    ).load()
    predictor = create_death_predictor(
        config=prediction_config,
        content=content,
        settings=settings,
    )
    schedule_interpreter = create_notification_schedule_interpreter(
        config=notification_schedule_config,
        content=content,
        settings=settings,
    )
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
        ssl=settings.postgres_ssl,
        pgbouncer=settings.postgres_pgbouncer,
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
        admin_user_ids=settings.telegram_admin_user_ids,
        metrics=metrics,
    )
    prepare = PrepareTelegramResponseActivities(
        response_store=response_documents,
        ttl_seconds=settings.telegram_update_ttl_seconds,
        content=content,
        mortals=mortals,
        notification_presets=notification_schedule_config.presets,
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
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    generate_prediction = GenerateDeathPredictionActivity(
        predictor=predictor,
        predictions=predictions,
        questionnaires=questionnaires,
        mortals=mortals,
        ttl_seconds=settings.questionnaire_ttl_seconds,
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
    prepare_notification = PrepareMortalNotificationActivity(
        mortals=mortals,
        responses=response_documents,
        presenter=NotificationMessagePresenter(
            content=content,
            number_speller=Num2WordsNumberSpeller.create(),
        ),
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
    logging.getLogger(__name__).info(
        "Telegram worker started",
        extra=LogContext(component="worker").event("application_started"),
    )
    try:
        async with worker:
            await stop_event.wait()
    finally:
        logging.getLogger(__name__).info(
            "Telegram worker stopping",
            extra=LogContext(component="worker").event("application_stopping"),
        )
        metrics_server.close()
        await predictor.close()
        await schedule_interpreter.close()
        await bot.session.close()
        await redis_connection.aclose()
        await postgres.close()


def main() -> None:
    settings = WorkerSettings()
    configure_logging(settings.log_level, settings.log_format, settings.app_name)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
