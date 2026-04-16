from __future__ import annotations

import logging
from pathlib import Path
from fastapi import Request, HTTPException, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.enums import UserRole
from src.services.auth_service import AuthService

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

async def get_db():
    """Dependency for database sessions."""
    async with SessionFactory() as session:
        yield session

async def get_bot(request: Request) -> Bot:
    """Возвращает экземпляр бота из состояния приложения."""
    return request.app.state.bot

async def get_current_user_payload(request: Request) -> dict:
    """Извлекает payload из JWT куки."""
    token = request.cookies.get("nexus_session")
    if not token:
        raise HTTPException(status_code=303, detail="Not authorized")
    
    payload = AuthService.decode_token(token)
    if not payload:
        raise HTTPException(status_code=303, detail="Invalid session")
    return payload

async def get_current_user(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Возвращает объект пользователя из БД."""
    user_id = payload.get("user_id")
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=303, detail="User not found")
    return user

class RoleChecker:
    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
