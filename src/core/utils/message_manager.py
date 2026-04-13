from __future__ import annotations

import logging
import time
from typing import Optional, Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message
from redis.asyncio import Redis

from src.core.config import get_settings
from src.core.utils.ui_builder import DIVIDER_LIGHT

logger = logging.getLogger(__name__)


class MessageManager:
    """
    Система Single Message Interface (SMI).
    Управляет «главным сообщением» пользователя, редактируя его вместо отправки новых.
    """

    def __init__(self, bot: Bot):
        self.bot = bot
        self.settings = get_settings()
        self._redis: Optional[Redis] = None
        if self.settings.redis_url:
            self._redis = Redis.from_url(self.settings.redis_url, decode_responses=True)

    async def _get_main_msg_id(self, key: str) -> Optional[int]:
        if not self._redis:
            return None
        val = await self._redis.get(f"smi_msg_id:{key}")
        return int(val) if val else None

    async def _set_main_msg_id(self, key: str, msg_id: int):
        if not self._redis:
            return
        await self._redis.set(f"smi_msg_id:{key}", msg_id, ex=86400 * 3)
        await self._redis.set(f"smi_last_ts:{key}", int(time.time()), ex=86400 * 3)

    async def _get_last_ts(self, key: str) -> int:
        if not self._redis:
            return 0
        val = await self._redis.get(f"smi_last_ts:{key}")
        return int(val) if val else 0

    async def display(
        self,
        event: Union[Message, CallbackQuery],
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        photo: Optional[str] = None,
        parse_mode: str = "HTML",
    ) -> None:
        """
        Основной метод отображения интерфейса.
        Поддерживает личные чаты, группы и топики.
        """
        user_id = event.from_user.id
        
        # Определяем ID чата и топика
        if isinstance(event, CallbackQuery):
            chat_id = event.message.chat.id
            thread_id = event.message.message_thread_id
        else:
            chat_id = event.chat.id
            thread_id = event.message_thread_id

        # Ключ в Redis зависит от чата (и топика, если есть)
        # Для ЛС chat_id == user_id
        cache_key = str(chat_id)
        if thread_id:
            cache_key = f"{chat_id}:{thread_id}"

        main_msg_id = await self._get_main_msg_id(cache_key)
        last_ts = await self._get_last_ts(cache_key)
        now = int(time.time())
        
        is_callback = isinstance(event, CallbackQuery)
        is_command = isinstance(event, Message)
        
        if is_callback:
            await self.answer_loading(event)

        force_new = False
        if is_command and main_msg_id:
            is_start = event.text and event.text.startswith("/start")
            # Если /start или сообщение очень старое (24ч) — пересоздаем
            if is_start or (now - last_ts > 86400):
                force_new = True

        if main_msg_id and not force_new:
            try:
                if photo:
                    await self.bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=main_msg_id,
                        media=InputMediaPhoto(media=photo, caption=text, parse_mode=parse_mode),
                        reply_markup=reply_markup,
                    )
                else:
                    await self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=main_msg_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                
                if self._redis:
                    await self._redis.set(f"smi_last_ts:{cache_key}", now, ex=86400 * 3)
                return
            except TelegramBadRequest as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return
                logger.debug(f"SMI Edit failed for {cache_key}, sending new message...")
                pass

        # ФИНАЛЬНЫЙ ЭТАП: Отправка нового сообщения
        try:
            if main_msg_id:
                try:
                    await self.bot.delete_message(chat_id, main_msg_id)
                except Exception:
                    pass

            if photo:
                new_msg = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    message_thread_id=thread_id
                )
            else:
                new_msg = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    message_thread_id=thread_id
                )

            await self._set_main_msg_id(cache_key, new_msg.message_id)
            
            # Уведомления только для ЛС (в группах они могут мешать)
            if chat_id == user_id:
                await self.ensure_notifications_below(user_id)

        except Exception as e:
            logger.error(f"SMI Critical error for {cache_key}: {e}")

    async def ensure_notifications_below(self, user_id: int):
        """Перемещает текущее уведомление в самый низ."""
        if not self._redis:
            return
            
        import pickle
        cache_key = f"notif_v4:{user_id}"
        try:
            raw = await self._redis.get(cache_key)
            if not raw:
                uid = await self._redis.get(f"tgid_to_uid:{user_id}")
                if uid:
                    cache_key = f"notif_v4:{uid}"
                    raw = await self._redis.get(cache_key)

            if not raw:
                return

            data = pickle.loads(raw)
            msg_id = data.get("msg_id")
            if not msg_id:
                return

            try:
                await self.bot.delete_message(user_id, msg_id)
            except Exception:
                pass
            
            data["msg_id"] = None
            await self._redis.set(cache_key, pickle.dumps(data), ex=3600)
        except Exception as e:
            logger.error(f"Error in ensure_notifications_below: {e}")

    async def send_notification(
        self,
        user_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        photo: Optional[str] = None,
        parse_mode: str = "HTML",
    ) -> Optional[int]:
        """Отправляет уведомление ниже главного меню."""
        chat_id = user_id
        if "❖" not in text:
            text = f"🔔 <b>GDPX // УВЕДОМЛЕНИЕ</b>\n{DIVIDER_LIGHT}\n{text}"

        try:
            if photo:
                msg = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            else:
                msg = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            return msg.message_id
        except Exception as e:
            logger.error(f"Error sending notification to {chat_id}: {e}")
            return None

    async def delete_main(self, user_id: int):
        """Полное удаление интерфейса."""
        msg_id = await self._get_main_msg_id(user_id)
        if msg_id:
            try:
                await self.bot.delete_message(user_id, msg_id)
            except Exception:
                pass
            if self._redis:
                await self._redis.delete(f"smi_msg_id:{user_id}")
                await self._redis.delete(f"smi_last_ts:{user_id}")

    async def answer_loading(self, callback: CallbackQuery):
        """Интеллектуальный ответ на callback."""
        text = "⏳ Обработка..."
        cd = callback.data or ""
        
        if "stats" in cd: text = "📊 Загружаю статистику..."
        elif "profile" in cd or "alias" in cd: text = "👤 Открываю профиль..."
        elif "sell" in cd or "category" in cd: text = "📡 Поиск операторов..."
        elif "leader" in cd: text = "🏆 Доска лидеров..."
        elif "academy" in cd: text = "🎓 Академия GDPX..."
        elif "notif" in cd: text = "🔔 Настройки уведомлений..."
        elif "finance" in cd or "payout" in cd: text = "💸 Финансовый мост..."
        elif "settings" in cd: text = "⚙️ Настройки..."
        elif "back" in cd or "main" in cd: text = "↩️ Возвращаюсь..."
        elif "moderation" in cd: text = "⚖️ Вход в модерацию..."
        elif "owner" in cd: text = "🏯 Командный центр..."

        try:
            await callback.answer(text, show_alert=False)
        except Exception:
            pass

    async def show_loading(self, callback: CallbackQuery):
        """Отображает временное состояние загрузки."""
        try:
            text = "⏳ <b>Подождите, идёт загрузка данных...</b>"
            if callback.message.photo:
                await self.bot.edit_message_caption(
                    chat_id=callback.from_user.id,
                    message_id=callback.message.message_id,
                    caption=text,
                    parse_mode="HTML"
                )
            else:
                await self.bot.edit_message_text(
                    chat_id=callback.from_user.id,
                    message_id=callback.message.message_id,
                    text=text,
                    parse_mode="HTML"
                )
        except Exception:
            pass
