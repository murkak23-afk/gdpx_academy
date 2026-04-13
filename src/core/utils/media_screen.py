"""Rich Media screen helpers — edit photo/animation inline with keyboard.

Позволяет «плавно» менять медиа и клавиатуру в одном сообщении, обходя
ограничения Telegram API.

────────────────────────────────────────────────────
Ограничения Telegram (важно знать):
────────────────────────────────────────────────────
✦ Можно переключать: photo ↔ photo, animation ↔ animation, video ↔ video.
✦ Нельзя одним вызовом: photo → animation (нужно удалить + отправить заново).
✦ Подпись (caption) редактируется через edit_message_caption, не edit_message_text.
✦ file_id из чужого бота не работает — используй собственные загрузки.

────────────────────────────────────────────────────
Паттерн использования в хендлере:
────────────────────────────────────────────────────
    # 1. Первый показ: отправляем медиа-сообщение
    sent = await MediaScreen.send_photo(
        message,
        photo=BANNER_FILE_ID,          # file_id ранее отправленного фото
        caption="<b>Главное меню</b>",
        reply_markup=main_keyboard(),
    )
    await state.update_data(screen_msg_id=sent.message_id)

    # 2. Обновление (edit in-place):
    msg_id = (await state.get_data()).get("screen_msg_id")
    await MediaScreen.edit_photo(
        callback,
        message_id=msg_id,
        photo=NEW_BANNER_FILE_ID,
        caption="<b>Профиль</b>",
        reply_markup=profile_keyboard(),
    )

────────────────────────────────────────────────────
file_id стратегия для GDPX:
────────────────────────────────────────────────────
    Храни file_id в .env / БД или в константах ниже.
    Загрузи баннеры один раз скриптом scripts/upload_banners.py
    и запиши file_id в BANNER_* константы.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    Message,
)
from loguru import logger

if TYPE_CHECKING:
    pass



# ── Константы: файл-идентификаторы баннеров ──────────────────────────────
# Заполни после первой загрузки (скриптом scripts/upload_banners.py).
# Placeholder-значения вызывают fallback на текстовый режим.

BANNER_MAIN = "AgACAgIAAxkBAAIIkmnQ-Xa1zILW1Lhx8vUtbofLwm2eAAIGFGsbryqISr7xTojIMylXAQADAgADeQADOwQ"      # file_id главного баннера продавца
BANNER_PROFILE = "AgACAgIAAxkBAAIIkGnQ-WfJMWZsupVz7y6mefbhSTMQAAIFFGsbryqISqEEsdhFsfqyAQADAgADeQADOwQ"
BANNER_MATERIALS = "AgACAgIAAxkBAAIIlGnQ-ZdM1yyht2pnY65pKk1-CRHYAAIHFGsbryqISsctltAvGAGBAQADAgADeQADOwQ"
BANNER_PAYHIST = "AgACAgIAAxkBAAIIlmnQ-aMtqLKCjfsECMJeFSuxIjq-AAIIFGsbryqISolNY-nQNqQmAQADAgADeQADOwQ"
BANNER_INFO = "AgACAgIAAxkBAAIIimnQ-RDif5UR9RDbfeg2C3K6jdkpAAIBFGsbryqISqOc-dgKWurfAQADAgADeQADOwQ"
BANNER_SUPPORT = "AgACAgIAAxkBAAIIiGnQ-L9PNz3HQikLuljDA4XObTz0AAL9E2sbryqIStmQ_kBDH7X9AQADAgADeQADOwQ"
BANNER_LEADERBOARD = "AgACAgIAAxkBAAIIjmnQ-VTIdIN3zD73xbzqBI7rsmndAAIEFGsbryqISvFIa_GYGl4uAQADAgADeQADOwQ"
BANNER_UPLOAD = "AgACAgIAAxkBAAIIjGnQ-TMUjmkj_2k5Z8kTwlAYlIDMAAIDFGsbryqISuTZ7GrMKT5qAQADAgADeQADOwQ"
BANNER_SUCCESS: str | None = None    # file_id анимации успеха (GIF/video)
BANNER_ERROR: str | None = None      # file_id анимации ошибки


# ── Core helpers ──────────────────────────────────────────────────────────


class MediaScreen:
    """Static helper для отправки и редактирования медиа-сообщений."""

    # ── Send ─────────────────────────────────────────────────────────────

    @staticmethod
    async def send_photo(
        message: Message,
        *,
        photo: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str = "HTML",
    ) -> Message:
        """Отправить фото с подписью и клавиатурой. Fallback на текст при невалидном file_id."""
        try:
            return await message.answer_photo(
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramBadRequest as exc:
            logger.warning("MediaScreen.send_photo: invalid file_id (%s), falling back to text", exc)
            return await message.answer(
                caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )

    @staticmethod
    async def send_animation(
        message: Message,
        *,
        animation: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str = "HTML",
    ) -> Message:
        """Отправить GIF/MP4-анимацию с подписью."""
        return await message.answer_animation(
            animation=animation,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    # ── Edit (inline swap) ────────────────────────────────────────────────

    @staticmethod
    async def edit_photo(
        callback: CallbackQuery,
        *,
        message_id: int | None = None,
        photo: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str = "HTML",
    ) -> None:
        """Редактировать медиа-сообщение: сменить фото + подпись + клавиатуру.

        Если message_id не передан — редактирует callback.message.
        """
        await callback.answer()
        target = callback.message
        if target is None:
            return

        try:
            await target.edit_media(
                media=InputMediaPhoto(
                    media=photo,
                    caption=caption,
                    parse_mode=parse_mode,
                ),
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            _log_media_edit_error(exc)

    @staticmethod
    async def edit_animation(
        callback: CallbackQuery,
        *,
        animation: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str = "HTML",
    ) -> None:
        """Редактировать медиа-сообщение: сменить анимацию + подпись."""
        await callback.answer()
        if callback.message is None:
            return
        try:
            await callback.message.edit_media(
                media=InputMediaAnimation(
                    media=animation,
                    caption=caption,
                    parse_mode=parse_mode,
                ),
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            _log_media_edit_error(exc)

    @staticmethod
    async def edit_caption_only(
        callback: CallbackQuery,
        *,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str = "HTML",
    ) -> None:
        """Сменить только текст подписи, не трогая медиа."""
        await callback.answer()
        if callback.message is None:
            return
        try:
            await callback.message.edit_caption(
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    # ── Transition helpers ────────────────────────────────────────────────

    @classmethod
    async def transition_photo(
        callback: "MediaScreen",
        self: CallbackQuery,
        *,
        photo: str | None,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str = "HTML",
    ) -> None:
        """Высокоуровневый переход: пробует edit_photo, при ошибке — caption only."""
        # Нормализуем сигнатуру — первый позиционный аргумент это callback
        cb = self  # type: ignore[assignment]
        if not isinstance(cb, CallbackQuery):
            # вызов как classmethod: callback = photo-аргумент (сигнатура выше перевёрнута)
            cb = callback  # type: ignore[assignment]
            photo = caption  # type: ignore[assignment]
        if photo and cb.message is not None:
            await MediaScreen.edit_photo(
                cb, photo=photo, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode
            )
        else:
            await MediaScreen.edit_caption_only(
                cb, caption=caption, reply_markup=reply_markup, parse_mode=parse_mode
            )


# ── Standalone transition function (рекомендуется) ────────────────────────


async def media_transition(
    callback: CallbackQuery,
    *,
    banner_file_id: str | None,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
    answered: bool = False,
) -> None:
    """Рекомендуемый способ обновить медиа-экран.

    Если ``banner_file_id`` задан — меняет фото.
    Если нет — редактирует только подпись (текст).

    Пример в хендлере (переход в профиль):

        @router.callback_query(F.data == CB_SELLER_MENU_PROFILE)
        async def on_profile(callback: CallbackQuery, session: AsyncSession) -> None:
            user = ...
            await media_transition(
                callback,
                banner_file_id=BANNER_PROFILE,
                caption=render_profile_text(user),
                reply_markup=profile_keyboard(),
            )
    """
    if not answered:
        await callback.answer()
    if callback.message is None:
        return

    msg = callback.message

    # Text-only messages (from send_clean_text_screen) don't support edit_caption / edit_media.
    # Delete and re-send as a fresh screen instead.
    if getattr(msg, "text", None) is not None and not getattr(msg, "photo", None):
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass
        if banner_file_id:
            try:
                await msg.answer_photo(
                    photo=banner_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except TelegramBadRequest as exc:
                logger.warning("media_transition: invalid banner file_id (%s), falling back to text", exc)
                await msg.answer(
                    caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
        else:
            await msg.answer(
                caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        return

    if banner_file_id:
        try:
            await msg.edit_media(
                media=InputMediaPhoto(
                    media=banner_file_id,
                    caption=caption,
                    parse_mode=parse_mode,
                ),
                reply_markup=reply_markup,
            )
            return
        except TelegramBadRequest as exc:
            logger.debug("media_transition: edit_media failed (%s), falling back to caption", exc)

    # Fallback 1: редактируем только подпись
    try:
        await msg.edit_caption(
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise

    # Fallback 2: подпись и фото не изменились — обновляем только клавиатуру.
    # Это случается когда edit_media/edit_caption возвращает "not modified" (одно и то же
    # фото + caption), но reply_markup другой (напр. collapsed → full menu).
    if reply_markup is not None:
        try:
            await msg.edit_reply_markup(reply_markup=reply_markup)
        except TelegramBadRequest as exc2:
            if "message is not modified" not in str(exc2).lower():
                raise


def _log_media_edit_error(exc: TelegramBadRequest) -> None:
    msg = str(exc).lower()
    if "message is not modified" in msg:
        return
    if "wrong type" in msg or "can't use" in msg:
        logger.warning(
            "MediaScreen: несовместимый тип медиа — смени тип или удали/перешли сообщение. %s", exc
        )
    else:
        logger.debug("MediaScreen: edit_media ошибка: %s", exc)
