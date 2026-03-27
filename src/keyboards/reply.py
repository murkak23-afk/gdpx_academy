from __future__ import annotations

from aiogram.types import (
    KeyboardButton,
    KeyboardButtonRequestChat,
    KeyboardButtonRequestUser,
    ReplyKeyboardMarkup,
)

from src.core.config import get_settings
from src.database.models.enums import UserLanguage, UserRole
from src.keyboards.constants import BUTTON_ENTER_ADMIN_PANEL, BUTTON_EXIT_ADMIN_PANEL, REPLY_BTN_BACK

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
    """Клавиатура выбора языка при регистрации."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Русский"), KeyboardButton(text="English")],
            [KeyboardButton(text="Polski")],
            [KeyboardButton(text=REPLY_BTN_BACK)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _norm_brand_url(raw: str | None) -> str | None:
    u = str(raw).strip() if raw else ""
    return u or None


def seller_main_menu_keyboard(
    *,
    language: UserLanguage = UserLanguage.RU,
    role: UserRole | None = None,
) -> ReplyKeyboardMarkup:
    """Главное меню селлера: опциональные кнопки-ссылки из BRAND_*_URL (пусто — кнопки нет)."""

    settings = get_settings()
    ru = language == UserLanguage.RU
    links: list[tuple[str, str | None]] = [
        ("КАНАЛ" if ru else "CHANNEL", _norm_brand_url(settings.brand_channel_url)),
        ("ЧАТ" if ru else "CHAT", _norm_brand_url(settings.brand_chat_url)),
        ("ВЫПЛАТЫ" if ru else "PAYMENTS", _norm_brand_url(settings.brand_payments_url)),
    ]

    rows: list[list[KeyboardButton]] = [[KeyboardButton(text="ПРОФИЛЬ")]]
    rows.append([KeyboardButton(text="Продать eSIM")])
    rows.append([KeyboardButton(text="Статистика"), KeyboardButton(text="INFO")])
    rows.append([KeyboardButton(text="Материал"), KeyboardButton(text="История выплат")])
    for label, url in links:
        if url:
            rows.append([KeyboardButton(text=label, url=url)])
    rows.append([KeyboardButton(text="Поддержка")])
    if role in (UserRole.CHIEF_ADMIN, UserRole.PAYOUT_ADMIN, UserRole.ADMIN):
        rows.append([KeyboardButton(text=BUTTON_ENTER_ADMIN_PANEL)])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
    )


def admin_main_menu_keyboard(*, show_payout_finance: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню админа: только админские разделы + выход (без кнопок «как у селлера»).

    «Статистика» и связанные финансовые разделы — только при show_payout_finance=True
    (chief_admin / payout_admin).
    """

    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="Очередь"), KeyboardButton(text="🏃 В работе")],
        [KeyboardButton(text="Отработанные")],
        [KeyboardButton(text="Выплаты")],
        [KeyboardButton(text="Рассылка"), KeyboardButton(text="Архив (7days)")],
    ]
    if show_payout_finance:
        rows.append([KeyboardButton(text="Статистика"), KeyboardButton(text=BUTTON_EXIT_ADMIN_PANEL)])
    else:
        rows.append([KeyboardButton(text=BUTTON_EXIT_ADMIN_PANEL)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
    )


def admin_payout_menu_keyboard() -> ReplyKeyboardMarkup:
    """Ограниченное меню админа выплат."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Выплаты"), KeyboardButton(text=BUTTON_EXIT_ADMIN_PANEL)],
        ],
        resize_keyboard=True,
    )


def categories_keyboard(category_titles: list[str]) -> ReplyKeyboardMarkup:
    """Клавиатура выбора категории для продажи."""

    category_rows: list[list[KeyboardButton]] = [[KeyboardButton(text=title)] for title in category_titles]
    category_rows.append([KeyboardButton(text=REPLY_BTN_BACK)])
    return ReplyKeyboardMarkup(
        keyboard=category_rows,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def seller_submission_step_keyboard() -> ReplyKeyboardMarkup:
    """Только «Назад» на шагах фото/описания."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=REPLY_BTN_BACK)]],
        resize_keyboard=True,
    )
