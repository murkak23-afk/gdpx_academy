"""Telegram Web App (TWA) helpers for GDPX.

Предоставляет:
    1. Билдер кнопок с WebApp URL (``web_app_button``)
    2. Типизированный DataClass для входящих ``web_app_data`` (``WebAppPayload``)
    3. Готовый Router с примером приёма данных от Mini App

──────────────────────────────────────────────────────
Какие узлы переводить в WebApp в первую очередь:
──────────────────────────────────────────────────────
СРОЧНО (нативный Telegram плохо справляется):
  • Каталог eSIM / выбор оператора — много карточек с фильтрами
  • Статистика продавца — графики (Chart.js / Recharts)
  • История выплат — таблица с сортировкой

ДОПУСТИМО ОСТАВИТЬ НАТИВНЫМ:
  • FSM загрузки материала (фото/документ) — Telegram нативно лучше
  • Модерация — inline-кнопки достаточны
  • Леадерборд — простой список

Конфигурация:
  Добавь в .env:
      WEBAPP_URL=https://yourapp.example.com
  Бот получает URL через settings.webapp_url и подставляет его в кнопки.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from aiogram import F, Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from loguru import logger

from src.core.config import get_settings

webapp_router = Router(name="webapp-router")

# ── Button builders ───────────────────────────────────────────────────────


def web_app_button(
    label: str,
    path: str,
    *,
    extra_params: dict[str, str] | None = None,
) -> InlineKeyboardButton:
    """Строит кнопку, открывающую Mini App.

    ``path`` — путь внутри вашего SPA, например ``/catalog`` или ``/stats``.
    ``extra_params`` — словарь GET-параметров (telegram_id подставляется всегда).

    Если WEBAPP_URL не задан в .env, кнопка не создаётся — вызывающие код
    должны гвардить через ``webapp_available()``.
    """
    base_url = (get_settings().webapp_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("WEBAPP_URL not set in .env")

    params: dict[str, str] = {}
    if extra_params:
        params.update(extra_params)

    qs = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{base_url}{path}{'?' + qs if qs else ''}"
    return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=full_url))


def webapp_available() -> bool:
    """True если WEBAPP_URL задан и Mini App может быть открыт."""
    return bool((get_settings().webapp_url or "").strip())


def catalog_webapp_keyboard(*, back_callback: str) -> InlineKeyboardMarkup:
    """Клавиатура для экрана каталога eSIM."""
    rows: list[list[InlineKeyboardButton]] = []
    if webapp_available():
        rows.append([web_app_button("📱 ОТКРЫТЬ КАТАЛОГ ESIM", "/catalog")])
    rows.append([InlineKeyboardButton(text="◀ НАЗАД", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stats_webapp_keyboard(*, telegram_id: int, back_callback: str) -> InlineKeyboardMarkup:
    """Клавиатура для экрана статистики продавца."""
    rows: list[list[InlineKeyboardButton]] = []
    if webapp_available():
        rows.append([
            web_app_button(
                "📊 ДЕТАЛЬНАЯ АНАЛИТИКА",
                "/stats",
                extra_params={"uid": str(telegram_id)},
            )
        ])
    rows.append([InlineKeyboardButton(text="◀ НАЗАД", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payout_webapp_keyboard(*, telegram_id: int, back_callback: str) -> InlineKeyboardMarkup:
    """Клавиатура для истории выплат."""
    rows: list[list[InlineKeyboardButton]] = []
    if webapp_available():
        rows.append([
            web_app_button(
                "💳 ИСТОРИЯ ВЫПЛАТ",
                "/payouts",
                extra_params={"uid": str(telegram_id)},
            )
        ])
    rows.append([InlineKeyboardButton(text="◀ НАЗАД", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Incoming data ─────────────────────────────────────────────────────────


@dataclass
class WebAppPayload:
    """Типизированная обёртка для данных из Mini App.

    Mini App отправляет: ``Telegram.WebApp.sendData(JSON.stringify({action, payload}))``
    """

    action: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: str) -> "WebAppPayload":
        """Парсит строку JSON из ``message.web_app_data.data``.

        Возвращает WebAppPayload с action="unknown" при ошибке парсинга.
        """
        try:
            data = json.loads(raw)
            return cls(
                action=str(data.get("action", "unknown")),
                payload=dict(data.get("payload", {})),
            )
        except (json.JSONDecodeError, AttributeError):
            logger.warning("WebApp: не удалось распарсить данные: %r", raw)
            return cls(action="unknown")


# ── Router: пример приёма данных из Mini App ─────────────────────────────
#
# Telegram отправляет web_app_data только через Reply-кнопку KeyboardButton(web_app=...).
# Inline WebApp кнопка НЕ триггерит web_app_data — её данные передаются через
# initData / sendData механизм Mini App API.
#
# Для inline-кнопок (InlineKeyboardButton) данные приходят через
# обычный HTTP к вашему API, а бот получает нотификацию через answerWebAppQuery.


@webapp_router.message(F.web_app_data)
async def on_webapp_data(message: Message) -> None:
    """Обрабатывает данные, отправленные из Mini App.

    Mini App (JS):
        Telegram.WebApp.sendData(JSON.stringify({
            action: "esim_selected",
            payload: { operator_id: 42, plan: "1GB" }
        }));
    """
    if message.web_app_data is None or message.from_user is None:
        return

    raw = message.web_app_data.data
    event = WebAppPayload.parse(raw)

    logger.info(
        "WebApp data: user_id=%s action=%s payload=%s",
        message.from_user.id,
        event.action,
        event.payload,
    )

    # Маршрутизация по action
    if event.action == "esim_selected":
        operator_id = event.payload.get("operator_id")
        plan = event.payload.get("plan", "—")
        await message.answer(
            f"✅ <b>ВЫБРАНА SIM:</b> ОПЕРАТОР - <code>{operator_id}</code>, ПЛАН <code>{plan}</code>\n\n"
            "ПОДТВЕРДИТЕ ЗАЯВКУ:",
            parse_mode="HTML",
        )

    elif event.action == "payout_request":
        amount = event.payload.get("amount", 0)
        await message.answer(
            f"💸 ЗАПРОС НА ВЫПЛАТУ <code>{amount}</code> USDT ПРИНЯТ.",
            parse_mode="HTML",
        )

    else:
        logger.warning("WebApp: НЕИЗВЕСТНЫЙ ACTION=%r", event.action)
        await message.answer("⚠️ ПОЛУЧЕНЫ НЕИЗВЕСТНЫЕ ДАННЫЕ ОТ ПРИЛОЖЕНИЯ.")
