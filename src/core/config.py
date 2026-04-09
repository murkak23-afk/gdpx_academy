from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator
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
    postgres_password: str = Field(default="tgpriem", alias="POSTGRES_PASSWORD")

    redis_url: str | None = Field(
        default=None,
        alias="REDIS_URL",
        description="URL Redis для FSM (например redis://localhost:6379/0). Пусто — MemoryStorage.",
    )

    http_host: str = Field(default="0.0.0.0", alias="HTTP_HOST")
    http_port: int = Field(default=8000, alias="HTTP_PORT")

    admin_telegram_ids: Any = Field(
        default_factory=list,
        validation_alias="ADMIN_TELEGRAM_IDS",
        description="Список ID администраторов (через запятую).",
    )

    moderation_chat_id: int = Field(
        default=0,
        validation_alias=AliasChoices("MODERATION_CHAT_ID", "ARCHIVE_CHAT_ID"),
    )
    crypto_pay_token: str | None = Field(default=None, alias="CRYPTO_PAY_TOKEN")
    crypto_asset: str = Field(default="USDT", alias="CRYPTO_ASSET")

    alert_telegram_chat_id: int | None = Field(
        default=None,
        alias="ALERT_TELEGRAM_CHAT_ID",
        description="Чат для служебных алертов (CryptoBot и т.д.). Пусто — не слать.",
    )
    admin_error_chat_id: int | None = Field(
        default=None,
        alias="ADMIN_ERROR_CHAT_ID",
        description="Чат для уведомлений о критических ошибках кода.",
    )
    maintenance_mode: bool = Field(
        default=False,
        alias="MAINTENANCE_MODE",
        description="Режим обслуживания: бот доступен только владельцам.",
    )
    owner_telegram_ids: Any = Field(
        default_factory=list,
        validation_alias="OWNER_TELEGRAM_IDS",
        description="ID владельцев, которые могут пользоваться ботом в Maintenance Mode.",
    )
    alert_cryptobot_cooldown_sec: int = Field(
        default=900,
        ge=60,
        le=86_400,
        alias="ALERT_CRYPTOBOT_COOLDOWN_SEC",
        description="Минимальный интервал между одинаковыми алертами CryptoBot, сек.",
    )
    health_ready_include_cryptobot: bool = Field(
        default=True,
        alias="HEALTH_READY_INCLUDE_CRYPTOBOT",
        description="Включать ли проверку Crypto Pay API в GET /health/ready (если задан CRYPTO_PAY_TOKEN).",
    )
    moderation_suspended: bool = Field(
        default=False,
        description="Глобальная приостановка работы всех модераторов.",
    )


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

    support_contact_founder: str | None = Field(default=None, alias="SUPPORT_CONTACT_FOUNDER")
    support_contact_architect: str | None = Field(default=None, alias="SUPPORT_CONTACT_ARCHITECT")
    support_contact_helper_1: str | None = Field(default=None, alias="SUPPORT_CONTACT_HELPER_1")
    support_contact_helper_2: str | None = Field(default=None, alias="SUPPORT_CONTACT_HELPER_2")
    chats: str | None = Field(default=None, alias="CHATS")

    @field_validator("maintenance_mode", "health_ready_include_cryptobot", "moderation_suspended", mode="before")
    @classmethod
    def _normalize_bool(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            val = value.strip().lower()
            if val in ("true", "1", "yes", "on"):
                return True
            if val in ("false", "0", "no", "off"):
                return False
            # Если в строке есть 'true' (даже с опечатками типа 'trueq'), считаем за True
            return "true" in val
        return bool(value)

    @field_validator("admin_telegram_ids", "owner_telegram_ids", mode="before")
    @classmethod
    def _normalize_admin_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, (int, float)):
            return [int(value)]
        if isinstance(value, list):
            return [int(v) for v in value if str(v).strip()]
        if isinstance(value, str):
            v = value.strip()
            # Убираем квадратные скобки, если они есть
            if v.startswith("[") and v.endswith("]"):
                v = v[1:-1]
            # Убираем все пробелы и разделяем по запятой
            items = [s.strip() for s in v.replace(" ", "").split(",") if s.strip()]
            return [int(i) for i in items]
        return []

    @field_validator("redis_url", mode="before")
    @classmethod
    def _normalize_redis_url(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value  # pragma: no cover

    @field_validator("alert_telegram_chat_id", mode="before")
    @classmethod
    def _normalize_alert_chat_id(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return None if value == 0 else value
        if isinstance(value, str):
            s = value.strip()
            if not s or s == "0":
                return None
            return int(s)
        return None

    @field_validator("crypto_asset", mode="before")
    @classmethod
    def _normalize_crypto_asset(cls, value: object) -> str:
        if value is None:
            return "USDT"
        if isinstance(value, str):
            normalized = value.strip().upper()
            return normalized or "USDT"
        return str(value).strip().upper() or "USDT"

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
