"""Application configuration loaded from environment variables."""

from functools import cached_property

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Validated runtime settings.

    ``.env`` is convenient for direct local runs. Docker Compose also passes the
    same file to the application container.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "sein-zum-tode"
    log_level: str = "INFO"

    telegram_bot_token: SecretStr

    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_database: str = "sein_zum_tode"
    postgres_user: str = "sein_zum_tode"
    postgres_password: SecretStr
    postgres_ssl: bool = False
    postgres_pgbouncer: bool = False

    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_database: int = Field(default=0, ge=0)
    redis_password: SecretStr

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "sein-zum-tode"
    temporal_tls: bool = False

    @cached_property
    def database_url(self) -> URL:
        query = {"prepared_statement_cache_size": "0"} if self.postgres_pgbouncer else {}
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
            query=query,
        )
