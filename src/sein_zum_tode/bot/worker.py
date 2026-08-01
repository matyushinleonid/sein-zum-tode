import asyncio

from aiogram import Bot
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
from sein_zum_tode.bot.conversation.activities import (
    RecordTelegramConversationAnswerActivity,
    StartTelegramConversationActivity,
)
from sein_zum_tode.bot.conversation.redis import RedisConversationStateRepository
from sein_zum_tode.bot.conversation.workflow import TelegramConversationWorkflow
from sein_zum_tode.bot.redis import RedisTelegramPayloadRepository
from sein_zum_tode.bot.sender import AiogramTelegramMessageSender
from sein_zum_tode.bot.workflow import TelegramUserWorkflow
from sein_zum_tode.config import WorkerSettings
from sein_zum_tode.infrastructure.postgres import PostgresClient
from sein_zum_tode.infrastructure.redis import RedisClient
from sein_zum_tode.infrastructure.yandex_ai import YandexAIStudioClient
from sein_zum_tode.localization.settings import ConfigureMortalLocalizationActivity
from sein_zum_tode.log_config import configure_logging
from sein_zum_tode.mortals.activities import MortalActivities
from sein_zum_tode.mortals.postgres import PostgresMortalRepository
from sein_zum_tode.notifications.activities import PrepareMortalNotificationActivity
from sein_zum_tode.notifications.settings import ConfigureMortalNotificationsActivity
from sein_zum_tode.notifications.temporal import TemporalMortalSchedule
from sein_zum_tode.notifications.workflow import MortalNotificationWorkflow
from sein_zum_tode.prediction.activities import (
    ApplyDeathPredictionActivity,
    GenerateDeathPredictionActivity,
    PreparePredictionFailureActivity,
)
from sein_zum_tode.prediction.config import (
    DeathPredictionConfig,
    PredictionConfigurationError,
    PredictionProvider,
    YamlDeathPredictionConfigLoader,
)
from sein_zum_tode.prediction.mock import MockDeathPredictor
from sein_zum_tode.prediction.ports import DeathPredictor
from sein_zum_tode.prediction.redis import RedisDeathPredictionRepository
from sein_zum_tode.prediction.yandex import YandexDeathPredictor
from sein_zum_tode.runtime import install_signal_handlers


def create_death_predictor(
    *,
    config: DeathPredictionConfig,
    content: BotContent,
    settings: WorkerSettings,
) -> DeathPredictor:
    if config.provider == PredictionProvider.MOCK:
        return MockDeathPredictor(
            config=config.mock,
            content=content,
        )
    if (
        settings.yandex_ai_studio_api_key is None
        or not settings.yandex_ai_studio_api_key.get_secret_value()
        or not settings.yandex_ai_studio_folder_id
    ):
        raise PredictionConfigurationError(
            "YANDEX_AI_STUDIO_API_KEY and YANDEX_AI_STUDIO_FOLDER_ID are required"
        )
    sdk = AsyncAIStudio(
        folder_id=settings.yandex_ai_studio_folder_id,
        auth=settings.yandex_ai_studio_api_key.get_secret_value(),
        enable_server_data_logging=config.yandex.enable_server_data_logging,
    )
    return YandexDeathPredictor(
        client=YandexAIStudioClient(
            sdk=sdk,
            config=config.yandex,
        )
    )


async def run(settings: WorkerSettings) -> None:
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    content = YamlBotContentLoader(settings.bot_content_path).load()
    prediction_config = YamlDeathPredictionConfigLoader(
        settings.death_prediction_config_path
    ).load()
    predictor = create_death_predictor(
        config=prediction_config,
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
    payloads = RedisTelegramPayloadRepository(redis)
    conversations = RedisConversationStateRepository(redis)
    predictions = RedisDeathPredictionRepository(redis)
    postgres = PostgresClient.create(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_database,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        ssl=settings.postgres_ssl,
        pgbouncer=settings.postgres_pgbouncer,
    )
    mortals = PostgresMortalRepository(postgres)
    schedules = TemporalMortalSchedule(
        client=temporal,
        bot_id=bot.id,
        task_queue=settings.temporal_task_queue,
        activity_retry_timeout_seconds=settings.temporal_activity_retry_timeout_seconds,
    )
    sender = AiogramTelegramMessageSender(bot)
    inspect = InspectTelegramUpdateActivity(payloads)
    prepare = PrepareTelegramResponseActivities(
        update_reader=payloads,
        response_store=payloads,
        ttl_seconds=settings.telegram_update_ttl_seconds,
        content=content,
        mortals=mortals,
    )
    start_conversation = StartTelegramConversationActivity(
        content=content,
        mortals=mortals,
        conversations=conversations,
        responses=payloads,
        conversation_ttl_seconds=settings.conversation_ttl_seconds,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        privacy_response_ttl_seconds=(
            settings.conversation_ttl_seconds + settings.temporal_activity_retry_timeout_seconds
        ),
    )
    record_answer = RecordTelegramConversationAnswerActivity(
        updates=payloads,
        conversations=conversations,
        responses=payloads,
        conversation_ttl_seconds=settings.conversation_ttl_seconds,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
        privacy_response_ttl_seconds=(
            settings.conversation_ttl_seconds + settings.temporal_activity_retry_timeout_seconds
        ),
    )
    deliver = DeliverTelegramResponseActivity(
        response_reader=payloads,
        sender=sender,
    )
    cleanup = CleanupTelegramPayloadsActivity(cleaner=payloads)
    mortal_activities = MortalActivities(
        mortals=mortals,
        schedules=schedules,
    )
    configure_notifications = ConfigureMortalNotificationsActivity(
        updates=payloads,
        responses=payloads,
        mortals=mortals,
        schedules=schedules,
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    configure_localization = ConfigureMortalLocalizationActivity(
        updates=payloads,
        responses=payloads,
        mortals=mortals,
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    generate_prediction = GenerateDeathPredictionActivity(
        predictor=predictor,
        predictions=predictions,
        conversations=conversations,
        mortals=mortals,
        ttl_seconds=settings.conversation_ttl_seconds,
    )
    apply_prediction = ApplyDeathPredictionActivity(
        predictions=predictions,
        mortals=mortals,
        schedules=schedules,
        responses=payloads,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    prepare_prediction_failure = PreparePredictionFailureActivity(
        mortals=mortals,
        responses=payloads,
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    prepare_notification = PrepareMortalNotificationActivity(
        mortals=mortals,
        responses=payloads,
        content=content,
        response_ttl_seconds=settings.telegram_update_ttl_seconds,
    )
    worker = Worker(
        temporal,
        task_queue=settings.temporal_task_queue,
        workflows=[
            TelegramUserWorkflow,
            TelegramConversationWorkflow,
            MortalNotificationWorkflow,
        ],
        activities=[
            inspect.inspect,
            prepare.prepare_echo,
            prepare.prepare_help,
            prepare.prepare_about,
            prepare.prepare_localization,
            prepare.prepare_notifications,
            prepare.prepare_limit_exhausted,
            prepare.prepare_unsupported,
            prepare.prepare_group_unsupported,
            start_conversation.start,
            record_answer.record,
            deliver.deliver,
            cleanup.cleanup,
            mortal_activities.ensure,
            mortal_activities.reset,
            mortal_activities.has_quota,
            mortal_activities.deactivate,
            mortal_activities.delete_schedule,
            prepare_notification.prepare,
            configure_localization.configure,
            configure_notifications.configure,
            generate_prediction.generate,
            apply_prediction.apply,
            prepare_prediction_failure.prepare,
        ],
    )
    try:
        async with worker:
            await stop_event.wait()
    finally:
        await bot.session.close()
        await redis_connection.aclose()
        await postgres.close()


def main() -> None:
    settings = WorkerSettings()
    configure_logging(settings.log_level, settings.log_format, settings.app_name)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
