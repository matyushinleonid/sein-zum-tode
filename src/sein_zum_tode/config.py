from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "sein-zum-tode-telegram-ingress"
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    telegram_bot_token: SecretStr
    telegram_polling_timeout_seconds: int = Field(default=30, ge=1)
    telegram_request_timeout_seconds: int = Field(default=40, ge=1)
    telegram_update_ttl_seconds: int = Field(default=3600, ge=1)
    questionnaire_ttl_seconds: int = Field(default=3600, ge=1)
    bot_content_path: Path = Path("config/bot-content.yaml")
    death_prediction_config_path: Path = Path("config/death-prediction.yaml")

    retry_initial_delay_seconds: float = Field(default=1.0, gt=0)
    retry_max_delay_seconds: float = Field(default=30.0, gt=0)

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "sein-zum-tode"
    temporal_tls: bool = False
    temporal_activity_retry_timeout_seconds: int = Field(default=300, ge=1)

    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_database: int = Field(default=0, ge=0)
    redis_password: SecretStr

    @model_validator(mode="after")
    def validate_activity_retry_timeout(self) -> Self:
        shortest_payload_ttl = min(
            self.telegram_update_ttl_seconds,
            self.questionnaire_ttl_seconds,
        )
        if self.temporal_activity_retry_timeout_seconds >= shortest_payload_ttl:
            raise ValueError(
                "TEMPORAL_ACTIVITY_RETRY_TIMEOUT_SECONDS must be less than "
                "TELEGRAM_UPDATE_TTL_SECONDS and QUESTIONNAIRE_TTL_SECONDS"
            )
        return self


class WorkerSettings(Settings):
    telegram_admin_user_ids: frozenset[int] = frozenset({162573173})
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_database: str = "sein_zum_tode"
    postgres_user: str = "sein_zum_tode"
    postgres_password: SecretStr
    postgres_ssl: bool = False
    postgres_pgbouncer: bool = False
    yandex_ai_studio_api_key: SecretStr | None = None
    yandex_ai_studio_folder_id: str | None = None
    yandex_ai_studio_enable_server_data_logging: bool = False
