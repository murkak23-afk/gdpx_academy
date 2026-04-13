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

    async def _get_main_msg_id(self, user_id: int) -> Optional[int]:
        if not self._redis:
            return None
        val = await self._redis.get(f"smi_msg_id:{user_id}")
        return int(val) if val else None

    async def _set_main_msg_id(self, user_id: int, msg_id: int):
        if not self._redis:
            return
        # Устанавливаем ID сообщения и обновляем время последнего взаимодействия
        await self._redis.set(f"smi_msg_id:{user_id}", msg_id, ex=86400 * 3)
        await self._redis.set(f"smi_last_ts:{user_id}", int(time.time()), ex=86400 * 3)

    async def _get_last_ts(self, user_id: int) -> int:
        if not self._redis:
            return 0
        val = await self._redis.get(f"smi_last_ts:{user_id}")
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
        Пробует редактировать существующее сообщение пользователя для плавности.
        """
        user_id = event.from_user.id
        main_msg_id = await self._get_main_msg_id(user_id)
        last_ts = await self._get_last_ts(user_id)
        now = int(time.time())
        
        is_callback = isinstance(event, CallbackQuery)
        is_command = isinstance(event, Message)
        
        # Авто-ответ на колбэк (убирает крутилку на кнопке)
        if is_callback:
            await self.answer_loading(event)

        # ЛОГИКА ПЕРЕЗАПУСКА (только если /start или сообщение очень старое)
        force_new = False
        if is_command and main_msg_id:
            is_start = event.text and event.text.startswith("/start")
            # Если прошло более 24 часов или это /start — пересоздаем интерфейс
            if is_start or (now - last_ts > 86400):
                force_new = True

        if main_msg_id and not force_new:
            try:
                # Если было фото и пришло новое фото — редактируем медиа (ПЛАВНО)
                if photo:
                    await self.bot.edit_message_media(
                        chat_id=user_id,
                        message_id=main_msg_id,
                        media=InputMediaPhoto(media=photo, caption=text, parse_mode=parse_mode),
                        reply_markup=reply_markup,
                    )
                else:
                    # Если фото нет, пробуем просто сменить текст
                    await self.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=main_msg_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                
                # Обновляем время активности
                if self._redis:
                    await self._redis.set(f"smi_last_ts:{user_id}", now, ex=86400 * 3)
                return
            except TelegramBadRequest as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return
                # Если нельзя редактировать (например, из текста в фото), идем к отправке нового
                logger.debug(f"SMI Edit failed (type mismatch?), sending new message...")
                pass

        # ФИНАЛЬНЫЙ ЭТАП: Отправка нового сообщения
        try:
            # Сначала удаляем старое (если оно есть), чтобы новое "всплыло" на его месте
            if main_msg_id:
                try:
                    await self.bot.delete_message(user_id, main_msg_id)
                except Exception:
                    pass

            if photo:
                new_msg = await self.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            else:
                new_msg = await self.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )

            await self._set_main_msg_id(user_id, new_msg.message_id)
            # Уведомления всегда "прилипают" снизу
            await self.ensure_notifications_below(user_id)

        except Exception as e:
            logger.error(f"SMI Critical error for {user_id}: {e}")

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
