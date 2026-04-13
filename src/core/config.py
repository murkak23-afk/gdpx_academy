from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Глобальные настройки приложения (Pydantic Settings)."""

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # --- SYSTEM ---
    env: str = Field(default="production", alias="ENV")  # production / development
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- BOT ---
    bot_token: str = Field(..., alias="BOT_TOKEN")
    bot_parse_mode: str = Field(default="HTML", alias="BOT_PARSE_MODE")

    # --- POSTGRES ---
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="tgpriem", alias="POSTGRES_DB")
    postgres_user: str = Field(default="tgpriem", alias="POSTGRES_USER")
    postgres_password: str = Field(default="tgpriem", alias="POSTGRES_PASSWORD")
    database_url_custom: str | None = Field(default=None, alias="DATABASE_URL")

    # --- REDIS ---
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    # --- HTTP ---
    http_host: str = Field(default="0.0.0.0", alias="HTTP_HOST")
    http_port: int = Field(default=8167, alias="HTTP_PORT")

    # --- WEBHOOK ---
    webhook_url: str = Field(default="https://gdpx.ru/webhook", alias="WEBHOOK_URL")
    webhook_secret_token: str = Field(default="secret-change-me-1234567890", alias="WEBHOOK_SECRET_TOKEN")
    webhook_path: str = Field(default="/webhook", alias="WEBHOOK_PATH")

    # --- CHATS ---
    admin_telegram_ids: Any = Field(default_factory=list, alias="ADMIN_TELEGRAM_IDS")
    owner_telegram_ids: Any = Field(default_factory=list, alias="OWNER_TELEGRAM_IDS")
    
    moderation_chat_id: int = Field(
        default=0, 
        validation_alias=AliasChoices("MODERATION_CHAT_ID", "ARCHIVE_CHAT_ID")
    )
    admin_error_chat_id: int | None = Field(default=None, alias="ADMIN_ERROR_CHAT_ID")
    alert_telegram_chat_id: int | None = Field(default=None, alias="ALERT_TELEGRAM_CHAT_ID")

    # --- CRYPTO ---
    crypto_pay_token: str | None = Field(default=None, alias="CRYPTO_PAY_TOKEN")
    crypto_asset: str = Field(default="USDT", alias="CRYPTO_ASSET")

    # --- SYSTEM ---
    maintenance_mode: bool = Field(default=False, alias="MAINTENANCE_MODE")
    moderation_suspended: bool = Field(default=False, alias="MODERATION_SUSPENDED")
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    # --- HEALTH ---
    health_ready_include_cryptobot: bool = Field(default=False, alias="HEALTH_READY_INCLUDE_CRYPTOBOT")
    
    # --- AUTO FIX ---
    auto_fix_enabled: bool = Field(default=True, alias="AUTO_FIX_ENABLED")
    auto_fix_chats: dict[int, dict[int, str]] = Field(default_factory=dict, alias="AUTO_FIX_CHATS")
    auto_fix_role: str = Field(default="simbuyer", alias="AUTO_FIX_ROLE")

    # --- BRAND ---
    brand_channel_url: str | None = Field(default=None, alias="BRAND_CHANNEL_URL")
    brand_chat_url: str | None = Field(default=None, alias="BRAND_CHAT_URL")
    brand_payments_url: str | None = Field(default=None, alias="BRAND_PAYMENTS_URL")

    # --- VALIDATORS ---

    @field_validator("maintenance_mode", "moderation_suspended", "auto_fix_enabled", mode="before")
    @classmethod
    def _normalize_bool(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    @field_validator("admin_telegram_ids", "owner_telegram_ids", mode="before")
    @classmethod
    def _normalize_ids(cls, v: Any) -> list[int]:
        if isinstance(v, str):
            if not v.strip(): return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v or []

    @field_validator("auto_fix_chats", mode="before")
    @classmethod
    def _parse_json_dict(cls, v: Any) -> dict[int, dict[int, str]]:
        if isinstance(v, str):
            v = v.strip()
            if not v: return {}
            import json
            try:
                data = json.loads(v)
                return {int(k): {int(tk): tv for tk, tv in val.items()} for k, val in data.items()}
            except:
                return {}
        return v or {}

    @property
    def database_url(self) -> str:
        if self.database_url_custom:
            return self.database_url_custom
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def alembic_database_url(self) -> str:
        if self.database_url_custom:
            # Превращаем asyncpg URL в psycopg URL для Alembic
            return self.database_url_custom.replace("asyncpg", "psycopg")
        return f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
