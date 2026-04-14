from __future__ import annotations

import logging
from fastapi import APIRouter, Form, Request, Response, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from src.database.session import SessionFactory
from src.database.models.web_control import WebAccount
from src.services.auth_service import AuthService

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
        
        # Устанавливаем защищенную куку
        response = RedirectResponse(url="/nexus", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key="nexus_session",
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
    response.delete_cookie("nexus_session")
    return response
