from __future__ import annotations

from functools import lru_cache
import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Глобальные настройки приложения из переменных окружения."""

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    bot_token: str = Field(..., alias="BOT_TOKEN")
    bot_parse_mode: str = Field(default="HTML", alias="BOT_PARSE_MODE")

    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="tgpriem", alias="POSTGRES_DB")
    postgres_user: str = Field(default="tgpriem", alias="POSTGRES_USER")
    postgres_password: str = Field(..., alias="POSTGRES_PASSWORD")

    archive_chat_id: int = Field(default=0, alias="ARCHIVE_CHAT_ID")

    brand_channel_url: str | None = Field(
        default=None,
        alias="BRAND_CHANNEL_URL",
        description="Ссылка на канал бренда (кнопка КАНАЛ / CHANNEL в меню селлера).",
    )
    brand_chat_url: str | None = Field(
        default=None,
        alias="BRAND_CHAT_URL",
        description="Ссылка на чат/группу бренда (кнопка ЧАТ / CHAT).",
    )
    brand_payments_url: str | None = Field(
        default=None,
        alias="BRAND_PAYMENTS_URL",
        description="Ссылка на выплаты (страница, бот, t.me — кнопка ВЫПЛАТЫ / PAYMENTS).",
    )

    @property
    def database_url(self) -> str:
        """Async URL для runtime-подключения через asyncpg."""

        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def alembic_database_url(self) -> str:
        """Sync URL для Alembic-миграций."""

        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кэшированный фабричный метод конфигурации."""

    return Settings()
