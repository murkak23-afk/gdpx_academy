from __future__ import annotations

import logging
import time
from typing import Optional, Union

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message
from src.core.utils.ui_builder import DIVIDER_LIGHT
from src.core.cache import get_redis

logger = logging.getLogger(__name__)

class MessageManager:
    """
    SMI (Single Message Interface) Manager v5.
    Обеспечивает работу интерфейса в одном сообщении с поддержкой групп и топиков.
    Индивидуально для каждого пользователя в общих чатах.
    """

    def __init__(self, bot: Bot, redis=None):
        self.bot = bot
        self._redis = redis

    async def _get_redis(self):
        if self._redis:
            return self._redis
        return await get_redis()

    async def _get_main_msg_id(self, cache_key: str) -> Optional[int]:
        redis = await self._get_redis()
        if not redis:
            return None
        res = await redis.get(f"smi_msg_id:{cache_key}")
        return int(res) if res else None

    async def _set_main_msg_id(self, cache_key: str, msg_id: int):
        redis = await self._get_redis()
        if redis:
            await redis.set(f"smi_msg_id:{cache_key}", msg_id, ex=86400 * 3)
            await redis.set(f"smi_last_ts:{cache_key}", int(time.time()), ex=86400 * 3)

    async def _get_last_ts(self, cache_key: str) -> int:
        redis = await self._get_redis()
        if not redis:
            return 0
        res = await redis.get(f"smi_last_ts:{cache_key}")
        return int(res) if res else 0

    async def display(
        self,
        event: Union[Message, CallbackQuery],
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        photo: Optional[str] = None,
        parse_mode: str = "HTML",
    ) -> int:
        """
        Основной метод отображения интерфейса.
        Возвращает ID актуального сообщения.
        """
        user_id = event.from_user.id
        redis = await self._get_redis()
        
        if isinstance(event, CallbackQuery):
            chat_id = event.message.chat.id
            thread_id = getattr(event.message, "message_thread_id", None)
        else:
            chat_id = event.chat.id
            thread_id = getattr(event, "message_thread_id", None)

        logger.info(f"SMI Display call: chat={chat_id}, thread={thread_id}, user={user_id}")

        # Индивидуальный ключ для групп/топиков
        if chat_id == user_id:
            cache_key = str(chat_id)
        else:
            cache_key = f"{chat_id}:{thread_id or 0}:{user_id}"

        main_msg_id = await self._get_main_msg_id(cache_key)
        last_ts = await self._get_last_ts(cache_key)
        now = int(time.time())
        
        logger.debug(f"SMI Logic for {cache_key}: main_msg_id={main_msg_id}, last_ts={last_ts}")
        
        is_callback = isinstance(event, CallbackQuery)
        is_command = isinstance(event, Message)
        
        if is_callback:
            await self.answer_loading(event)

        # Флаг принудительной отправки нового сообщения
        force_new = False
        if is_command:
            cmd_text = (event.text or "").lower()
            if cmd_text.startswith(("/qr", "/qrweb", "/start", "/a", "/o")):
                force_new = True
                logger.info(f"SMI: Force NEW message for command '{cmd_text}' in {cache_key}")
            elif main_msg_id and (now - last_ts > 86400):
                force_new = True
                logger.info(f"SMI: Force NEW due to timeout in {cache_key}")

        # Если есть старое сообщение и МЫ НЕ ХОТИМ НОВОЕ - пробуем редактировать
        if main_msg_id and not force_new:
            try:
                logger.debug(f"SMI: Attempting EDIT for {main_msg_id} in {cache_key}")
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
                return main_msg_id
            except Exception as e:
                err_msg = str(e).lower()
                if "message is not modified" in err_msg:
                    return main_msg_id
                
                logger.warning(f"SMI Edit failed ({e}), forcing NEW for {cache_key}")
                # Если редактирование не вышло (например, старое было фото, а новое текст)
                # Пытаемся удалить и идем дальше к отправке нового
                try: 
                    await self.bot.delete_message(chat_id, main_msg_id)
                    logger.info(f"SMI: Deleted old message {main_msg_id} after edit failure")
                except: pass
                main_msg_id = None

        # ОТПРАВКА НОВОГО СООБЩЕНИЯ
        try:
            # Если мы сюда попали и main_msg_id еще есть (force_new) - удаляем
            if main_msg_id:
                try: 
                    await self.bot.delete_message(chat_id, main_msg_id)
                    logger.info(f"SMI: Deleted old message {main_msg_id} before sending NEW")
                except Exception as e:
                    logger.warning(f"SMI: Failed to delete old {main_msg_id}: {e}")

            if photo:
                new_msg = await self.bot.send_photo(
                    chat_id=chat_id, photo=photo, caption=text,
                    reply_markup=reply_markup, parse_mode=parse_mode,
                    message_thread_id=thread_id
                )
            else:
                new_msg = await self.bot.send_message(
                    chat_id=chat_id, text=text,
                    reply_markup=reply_markup, parse_mode=parse_mode,
                    message_thread_id=thread_id
                )
            
            logger.info(f"SMI: Sent NEW message {new_msg.message_id} for {cache_key}")
            await self._set_main_msg_id(cache_key, new_msg.message_id)
            return new_msg.message_id
        except Exception as e:
            logger.error(f"SMI NEW SEND FAILED: chat={chat_id}, thread={thread_id}. Error: {e}")
            # Последний шанс: шлем простым текстом без наворотов
            try:
                err_info = await self.bot.send_message(chat_id, f"⚠️ Ошибка интерфейса: {e}", message_thread_id=thread_id)
                return err_info.message_id
            except:
                return 0

    async def ensure_notifications_below(self, user_id: int):
        """Перемещает текущее уведомление в самый низ (для ЛС)."""
        redis = await self._get_redis()
        if not redis: return
        import pickle
        cache_key = f"notif_v4:{user_id}"
        try:
            raw = await redis.get(cache_key)
            if not raw: return
            data = pickle.loads(raw)
            msg_id = data.get("msg_id")
            if not msg_id: return
            try: await self.bot.delete_message(user_id, msg_id)
            except: pass
            data["msg_id"] = None
            await redis.set(cache_key, pickle.dumps(data), ex=3600)
        except Exception as e: logger.error(f"Error in ensure_notifications_below: {e}")

    async def send_notification(self, user_id: int, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, photo: Optional[str] = None, parse_mode: str = "HTML") -> Optional[int]:
        """Отправляет уведомление."""
        if "❖" not in text: text = f"🔔 <b>GDPX // УВЕДОМЛЕНИЕ</b>\n{DIVIDER_LIGHT}\n{text}"
        try:
            if photo:
                msg = await self.bot.send_photo(chat_id=user_id, photo=photo, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                msg = await self.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            return msg.message_id
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return None

    async def delete_main(self, event: Union[Message, CallbackQuery] = None, user_id: int = None):
        """Полное удаление интерфейса (поддерживает группы и топики)."""
        if event:
            u_id = event.from_user.id
            if isinstance(event, CallbackQuery):
                chat_id = event.message.chat.id
                thread_id = event.message.message_thread_id
            else:
                chat_id = event.chat.id
                thread_id = event.message_thread_id
        else:
            u_id = user_id
            chat_id = user_id
            thread_id = None

        if chat_id == u_id:
            cache_key = str(chat_id)
        else:
            cache_key = f"{chat_id}:{thread_id or 0}:{u_id}"

        msg_id = await self._get_main_msg_id(cache_key)
        redis = await self._get_redis()
        
        if msg_id:
            try: await self.bot.delete_message(chat_id, msg_id)
            except: pass
            if redis:
                await redis.delete(f"smi_msg_id:{cache_key}")
                await redis.delete(f"smi_last_ts:{cache_key}")

    async def answer_loading(self, callback: CallbackQuery):
        """Ответ на callback."""
        text = "⏳ Обработка..."
        cd = callback.data or ""
        if "stats" in cd: text = "📊 Статистика..."
        elif "profile" in cd: text = "👤 Профиль..."
        elif "sell" in cd: text = "📡 Поиск операторов..."
        try: await callback.answer(text)
        except: pass

    async def show_loading(self, callback: CallbackQuery):
        """Алиас для обратной совместимости."""
        await self.answer_loading(callback)
