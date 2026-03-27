"""FastAPI-приложение: healthcheck и задел под WebApp."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.config import get_settings
from src.database.session import engine
from src.services.cryptobot_service import CryptoBotService


def create_app() -> FastAPI:
    app = FastAPI(
        title="tgpriem API",
        version="1.0.0",
        description="Служебные эндпоинты и будущие WebApp-интеграции.",
    )

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
