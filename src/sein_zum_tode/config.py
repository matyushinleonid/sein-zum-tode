from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "sein-zum-tode-telegram-ingress"
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"

    telegram_bot_token: SecretStr
    telegram_polling_timeout_seconds: int = Field(default=30, ge=1)
    telegram_request_timeout_seconds: int = Field(default=40, ge=1)
    telegram_update_ttl_seconds: int = Field(default=3600, ge=1)

    retry_initial_delay_seconds: float = Field(default=1.0, gt=0)
    retry_max_delay_seconds: float = Field(default=30.0, gt=0)

    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_database: int = Field(default=0, ge=0)
    redis_password: SecretStr
