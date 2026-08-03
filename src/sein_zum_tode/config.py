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
    metrics_host: str = "0.0.0.0"
    metrics_port: int = Field(default=8000, ge=1, le=65535)
    health_host: str = "0.0.0.0"
    health_port: int = Field(default=8001, ge=1, le=65535)
    health_check_interval_seconds: float = Field(default=10.0, gt=0)
    health_check_timeout_seconds: float = Field(default=3.0, gt=0)
    health_liveness_timeout_seconds: float = Field(default=30.0, gt=0)
    health_success_threshold: int = Field(default=1, ge=1)
    health_failure_threshold: int = Field(default=2, ge=1)
    broadcast_recipient_page_size: int = Field(default=100, ge=1, le=1000)

    telegram_bot_token: SecretStr
    telegram_polling_timeout_seconds: int = Field(default=30, ge=1)
    telegram_request_timeout_seconds: int = Field(default=40, ge=1)
    telegram_update_ttl_seconds: int = Field(default=3600, ge=1)
    questionnaire_ttl_seconds: int = Field(default=3600, ge=1)
    bot_content_path: Path = Path("config/bot-content.yaml")
    death_prediction_config_path: Path = Path("config/death-prediction.yaml")
    notification_schedule_config_path: Path = Path("config/notification-schedule.yaml")

    retry_initial_delay_seconds: float = Field(default=1.0, gt=0)
    retry_max_delay_seconds: float = Field(default=30.0, gt=0)

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "sein-zum-tode"
    temporal_tls: bool = False
    temporal_tls_server_name: str | None = None
    temporal_tls_ca_file: Path | None = None
    temporal_tls_certificate_file: Path | None = None
    temporal_tls_private_key_file: Path | None = None
    temporal_activity_retry_timeout_seconds: int = Field(default=300, ge=1)

    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_database: int = Field(default=0, ge=0)
    redis_username: str | None = None
    redis_password: SecretStr
    redis_socket_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    redis_socket_timeout_seconds: float = Field(default=5.0, gt=0)
    redis_max_connections: int | None = Field(default=None, ge=1)
    redis_health_check_interval_seconds: int = Field(default=30, ge=0)
    redis_tls: bool = False
    redis_tls_verify: bool = True
    redis_tls_ca_file: Path | None = None
    redis_tls_certificate_file: Path | None = None
    redis_tls_private_key_file: Path | None = None

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

    @model_validator(mode="after")
    def validate_health_settings(self) -> Self:
        if self.health_port == self.metrics_port:
            raise ValueError("HEALTH_PORT and METRICS_PORT must be different")
        minimum_liveness_timeout = (
            self.health_check_interval_seconds + self.health_check_timeout_seconds
        )
        if self.health_liveness_timeout_seconds <= minimum_liveness_timeout:
            raise ValueError(
                "HEALTH_LIVENESS_TIMEOUT_SECONDS must exceed the health check interval and timeout"
            )
        return self

    @model_validator(mode="after")
    def validate_client_certificates(self) -> Self:
        pairs = (
            (
                self.redis_tls_certificate_file,
                self.redis_tls_private_key_file,
                "Redis",
            ),
            (
                self.temporal_tls_certificate_file,
                self.temporal_tls_private_key_file,
                "Temporal",
            ),
        )
        for certificate, private_key, service in pairs:
            if (certificate is None) != (private_key is None):
                raise ValueError(f"{service} TLS certificate and private key must be set together")
        return self


class WorkerSettings(Settings):
    telegram_admin_user_ids: frozenset[int] = frozenset()
    unsupported_update_session_ttl_seconds: int = Field(default=3600, ge=1)
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_database: str = "sein_zum_tode"
    postgres_user: str = "sein_zum_tode"
    postgres_password: SecretStr
    postgres_tls_mode: Literal["disable", "require", "verify-ca", "verify-full"] = "disable"
    postgres_tls_ca_file: Path | None = None
    postgres_tls_certificate_file: Path | None = None
    postgres_tls_private_key_file: Path | None = None
    postgres_pgbouncer: bool = False
    postgres_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    postgres_pool_size: int = Field(default=5, ge=1)
    postgres_max_overflow: int = Field(default=10, ge=0)
    postgres_pool_timeout_seconds: float = Field(default=30.0, gt=0)
    postgres_pool_recycle_seconds: int = Field(default=-1, ge=-1)
    yandex_ai_studio_api_key: SecretStr | None = None
    yandex_ai_studio_folder_id: str | None = None
    yandex_ai_studio_enable_server_data_logging: bool = False
    openai_api_key: SecretStr | None = None
    socks5_proxy_host: str | None = None
    socks5_proxy_port: int | None = Field(default=None, ge=1, le=65535)
    socks5_proxy_username: str | None = None
    socks5_proxy_password: SecretStr | None = None

    @model_validator(mode="after")
    def validate_unsupported_session_retry_timeout(self) -> Self:
        if (
            self.temporal_activity_retry_timeout_seconds
            >= self.unsupported_update_session_ttl_seconds
        ):
            raise ValueError(
                "TEMPORAL_ACTIVITY_RETRY_TIMEOUT_SECONDS must be less than "
                "UNSUPPORTED_UPDATE_SESSION_TTL_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def validate_postgres_client_certificate(self) -> Self:
        if (self.postgres_tls_certificate_file is None) != (
            self.postgres_tls_private_key_file is None
        ):
            raise ValueError("PostgreSQL TLS certificate and private key must be set together")
        return self
