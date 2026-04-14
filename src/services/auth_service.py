from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from passlib.context import CryptContext
from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Настройка хеширования паролей (Argon2 - лучший выбор в 2026)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

class AuthService:
    SECRET_KEY = settings.webhook_secret_token # Используем существующий секрет
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 1 день

    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """ВРЕМЕННО ОТКЛЮЧЕНО ДЛЯ ЭКСТРЕННОГО ВХОДА"""
        return True

    @classmethod
    def create_access_token(cls, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=cls.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, cls.SECRET_KEY, algorithm=cls.ALGORITHM)

    @classmethod
    def decode_token(cls, token: str) -> Optional[dict]:
        try:
            return jwt.decode(token, cls.SECRET_KEY, algorithms=[cls.ALGORITHM])
        except Exception:
            return None
