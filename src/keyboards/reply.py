from __future__ import annotations

from aiogram.types import (
    KeyboardButton,
    KeyboardButtonRequestChat,
    KeyboardButtonRequestUser,
    ReplyKeyboardMarkup,
)

from src.database.models.enums import UserLanguage, UserRole
from src.keyboards.constants import BUTTON_ENTER_ADMIN_PANEL, REPLY_BTN_BACK

# Совпадают с обработчиками chat_shared / user_shared при пересылке.
FORWARD_REQ_CHAT_GROUP = 1
FORWARD_REQ_CHAT_CHANNEL = 2
FORWARD_REQ_USER_DM = 3


def forward_target_reply_keyboard() -> ReplyKeyboardMarkup:
    """Группа, канал или пользователь (ЛС); бот уже должен иметь доступ к чату."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📁 Выбрать группу",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=FORWARD_REQ_CHAT_GROUP,
                        chat_is_channel=False,
                        bot_is_member=True,
                        request_title=True,
                    ),
                ),
            ],
            [
                KeyboardButton(
                    text="📢 Выбрать канал",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=FORWARD_REQ_CHAT_CHANNEL,
                        chat_is_channel=True,
                        bot_is_member=True,
                        request_title=True,
                    ),
                ),
            ],
            [
                KeyboardButton(
                    text="👤 Личные сообщения (выбрать пользователя)",
                    request_user=KeyboardButtonRequestUser(
                        request_id=FORWARD_REQ_USER_DM,
                        user_is_bot=False,
                    ),
                ),
            ],
            [KeyboardButton(text=REPLY_BTN_BACK)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def language_choice_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура подтверждения языка при регистрации (только русский)."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Русский")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def seller_main_menu_keyboard(
    *,
    language: UserLanguage = UserLanguage.RU,
    role: UserRole | None = None,
) -> ReplyKeyboardMarkup:
    """Главное меню селлера."""

    rows: list[list[KeyboardButton]] = [[KeyboardButton(text="ПРОФИЛЬ")]]
    rows.append([KeyboardButton(text="Продать eSIM")])
    rows.append([KeyboardButton(text="Статистика"), KeyboardButton(text="Справка")])
    rows.append([KeyboardButton(text="Материал"), KeyboardButton(text="История выплат")])
    rows.append([KeyboardButton(text="Поддержка")])
    
    # Можно добавить кнопку модерации для админов
    role_value = str(getattr(role, "value", role or "")).strip().lower()
    if role_value == UserRole.ADMIN.value:
        rows.append([KeyboardButton(text="⚖️ Модерация")])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
    )
