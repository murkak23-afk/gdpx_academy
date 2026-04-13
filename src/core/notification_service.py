from __future__ import annotations

import logging
import traceback
from datetime import datetime
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

    from src.core.config import Settings

logger = logging.getLogger(__name__)

class NotificationService:
    """Сервис для отправки уведомлений и алертов администраторам."""

    def __init__(self, bot: Bot, settings: Settings) -> None:
        self._bot = bot
        self._settings = settings

    async def notify_critical_error(
        self,
        exc: Exception,
        update_id: int | None = None,
        user_id: int | None = None,
    ) -> bool:
        """Отправляет детализированный отчет о критической ошибке в чат админов."""
        
        # 1. ЗАЩИТА ОТ РЕКУРСИИ: не шлем алерты об ошибках сети самого Telegram
        exc_str = str(exc).lower()
        if any(x in exc_str for x in ["timeout", "resolution", "retry after", "network error", "connector"]):
            logger.debug("Skipping Telegram alert for network-related error to avoid loop.")
            return False

        chat_id = self._settings.admin_error_chat_id
        if not chat_id:
            return False

        # 2. ДЕБАУНС: не шлем одну и ту же ошибку чаще раза в 5 минут
        error_type = type(exc).__name__
        from src.core.cache import get_redis
        redis = await get_redis()
        if redis:
            cache_key = f"alert_debounce:{error_type}:{str(exc)[:50]}"
            if await redis.get(cache_key):
                return False
            await redis.set(cache_key, "1", ex=300)

        error_msg = escape(str(exc))
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=10))
        tb_escaped = escape(tb_str)

        text = (
            f"🚨 <b>#КРИТИЧЕСКАЯ_ОШИБКА</b>\n"
            f"📅 <b>Время:</b> <code>{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC</code>\n"
            f"🏷 <b>Тип:</b> <code>{error_type}</code>\n"
            f"🆔 <b>Update ID:</b> <code>{update_id or 'N/A'}</code>\n"
            f"👤 <b>User ID:</b> <code>{user_id or 'N/A'}</code>\n\n"
            f"💬 <b>Сообщение:</b>\n<pre>{error_msg[:500]}</pre>\n\n"
            f"📋 <b>Traceback:</b>\n<pre><code class='language-python'>{tb_escaped[:2500]}</code></pre>"
        )

        try:
            from src.core.utils.message_manager import MessageManager
            mm = MessageManager(self._bot)
            await mm.send_notification(
                user_id=chat_id,
                text=text,
                parse_mode="HTML",
            )
            return True
        except Exception as e:
            # Используем стандартный принт или логгер, который НЕ перехватывается, 
            # чтобы избежать бесконечной рекурсии при ошибках сети/flood
            print(f"CRITICAL: Ошибка при отправке алерта в чат {chat_id}: {e}")
            return False

    async def send_system_alert(self, message: str) -> bool:
        """Отправляет произвольное системное уведомление в чат алертов."""
        msg_lower = message.lower()
        # Избегаем зацикливания на ошибках логгера или сети
        if any(x in msg_lower for x in ["timeout", "resolution", "retry after", "network error", "connector"]):
            return False

        chat_id = self._settings.alert_telegram_chat_id or self._settings.admin_error_chat_id
        if not chat_id:
            return False

        try:
            from src.core.utils.message_manager import MessageManager
            mm = MessageManager(self._bot)
            # Экранируем сообщение, чтобы символы < и > не ломали HTML
            safe_message = escape(message) if "<b>" not in message else message
            await mm.send_notification(
                user_id=chat_id,
                text=f"🔔 <b>System Alert:</b>\n\n{safe_message}",
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"CRITICAL: Ошибка при отправке системного алерта: {e}")
            return False
