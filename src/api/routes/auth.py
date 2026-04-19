from __future__ import annotations

import logging
import hmac
import hashlib
import json
from fastapi import APIRouter, Form, Request, Response, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from src.database.session import SessionFactory
from src.database.models.web_control import WebAccount
from src.services.auth_service import AuthService

from urllib.parse import parse_qsl

def verify_telegram_webapp_data(init_data: str, bot_token: str) -> dict | None:
    """Проверяет хеш данных WebApp от Telegram."""
    try:
        vals = dict(parse_qsl(init_data))
        hash_val = vals.pop("hash", None)
        if not hash_val:
            return None

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(vals.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if h == hash_val:
            return json.loads(vals.get("user", "{}"))
        return None
    except Exception:
        return None

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger(__name__)

@router.get("/login", response_class=HTMLResponse)
async def get_login_page(request: Request):
    """Отдает страницу логина."""
    from src.api.app import templates
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def post_login(
    response: Response,
    login: str = Form(...),
    password: str = Form(...),
):
    """Проверка данных и выдача токена."""
    async with SessionFactory() as session:
        # Ищем аккаунт
        stmt = select(WebAccount).where(WebAccount.login == login)
        result = await session.execute(stmt)
        account = result.scalar_one_or_none()

        if not account or not AuthService.verify_password(password, account.password_hash):
            # HTMX ответ с ошибкой
            return HTMLResponse(
                content='<div class="bg-red-900/20 border border-red-900 text-red-400 p-3 rounded-lg text-xs text-center">Неверный логин или пароль</div>',
                status_code=200
            )

        # Создаем токен
        token = AuthService.create_access_token(data={"sub": account.login, "user_id": account.user_id})
        
        # Устанавливаем защищенную куку и даем команду HTMX перенаправить страницу
        response = RedirectResponse(url="/gdpx", status_code=303)
        response.set_cookie(
            key="gdpx_session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=True
        )
        return response

@router.get("/logout")
async def logout():
    """Сброс сессии."""
    response = RedirectResponse(url="/auth/login")
    response.delete_cookie("gdpx_session")
    return response
