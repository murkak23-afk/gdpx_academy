"""FastAPI-приложение: healthcheck и задел под WebApp."""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(
        title="tgpriem API",
        version="1.0.0",
        description="Служебные эндпоинты и будущие WebApp-интеграции.",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
