"""FastAPI-приложение: healthcheck и задел под WebApp."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy import text
from aiogram import Dispatcher, Bot
from aiogram.types import Update

from src.core.config import get_settings
from src.database.session import engine
from src.domain.finance.cryptobot_service import CryptoBotService

logger = logging.getLogger(__name__)


def create_app(bot: Bot, dispatcher: Dispatcher) -> FastAPI:
    app = FastAPI(
        title="tgpriem API",
        version="1.0.0",
        description="Служебные эндпоинты и Webhook-интеграция.",
    )
    settings = get_settings()

    @app.post(settings.webhook_path)
    async def telegram_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        x_telegram_bot_api_secret_token: str | None = Header(None),
    ) -> Any:
        """Эндпоинт для приёма обновлений от Telegram."""
        if x_telegram_bot_api_secret_token != settings.webhook_secret_token:
            logger.warning("Unauthorized webhook request with invalid secret token.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        
        # Передаём обработку в фон, чтобы мгновенно вернуть Telegram {"ok": True}
        background_tasks.add_task(dispatcher.feed_update, bot, update)
        return {"ok": True}

    @app.get("/health")
    async def health_legacy() -> dict[str, str]:
        """Обратная совместимость: только liveness процесса."""

        return {"status": "ok"}

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        """Liveness: процесс отвечает (без БД и внешних API)."""

        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        """Readiness: БД и опционально Crypto Pay API."""

        checks: dict[str, str] = {}
        settings = get_settings()

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"

        crypto_failed = False
        if settings.health_ready_include_cryptobot and settings.crypto_pay_token:
            try:
                await CryptoBotService().get_balance()
                checks["cryptobot"] = "ok"
            except Exception as exc:
                crypto_failed = True
                checks["cryptobot"] = f"error: {type(exc).__name__}"
        else:
            checks["cryptobot"] = "skipped"

        db_ok = checks.get("database") == "ok"
        ready = db_ok and not crypto_failed
        body: dict[str, Any] = {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
        }
        return JSONResponse(status_code=200 if ready else 503, content=body)

    return app
