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
        chat_id = self._settings.admin_error_chat_id
        if not chat_id:
            logger.warning("ADMIN_ERROR_CHAT_ID не настроен. Алерт пропущен.")
            return False

        error_type = type(exc).__name__
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
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception as e:
            # Используем стандартный принт или логгер, который НЕ перехватывается, 
            # чтобы избежать бесконечной рекурсии при ошибках сети/flood
            print(f"CRITICAL: Ошибка при отправке алерта в чат {chat_id}: {e}")
            return False

    async def send_system_alert(self, message: str) -> bool:
        """Отправляет произвольное системное уведомление в чат алертов."""
        chat_id = self._settings.alert_telegram_chat_id or self._settings.admin_error_chat_id
        if not chat_id:
            return False

        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=f"🔔 <b>System Alert:</b>\n\n{message}",
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"CRITICAL: Ошибка при отправке системного алерта: {e}")
            return False
