from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.admin_audit import AdminAuditLog
from src.keyboards import REPLY_BTN_BACK
from src.keyboards.admin_hints import HINT_BROADCAST
from src.keyboards.callbacks import (
    CB_ADMIN_BROADCAST,
    CALLBACK_INLINE_BACK,
)
from src.services import (
    AdminAuditService,
    AdminService,
    UserService,
)
from src.states.admin_state import AdminBroadcastState
from src.utils.text_format import edit_message_text_safe

router = Router(name="admin-mailing-router")
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────


async def _notify_bulk_with_progress(
    bot: Bot,
    notifications: list[tuple[int, str]],
    *,
    concurrency: int = 20,
    progress_step: int = 10,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Параллельно отправляет уведомления с ограничением и прогрессом."""

    total = len(notifications)
    if total == 0:
        return 0, 0

    sem = asyncio.Semaphore(max(concurrency, 1))
    lock = asyncio.Lock()
    ok_count = 0
    fail_count = 0
    processed = 0

    async def _send_one(chat_id: int, text: str) -> None:
        nonlocal ok_count, fail_count, processed
        try:
            async with sem:
                await bot.send_message(chat_id=chat_id, text=text)
            ok = True
        except TelegramAPIError:
            ok = False

        should_report = False
        processed_now = 0
        async with lock:
            processed += 1
            if ok:
                ok_count += 1
            else:
                fail_count += 1
            processed_now = processed
            should_report = processed_now % max(progress_step, 1) == 0 or processed_now == total

        if should_report and on_progress is not None:
            await on_progress(processed_now, total)

    await asyncio.gather(*(_send_one(chat_id, text) for chat_id, text in notifications))
    return ok_count, fail_count


# ── handlers ─────────────────────────────────────────────────


@router.callback_query(F.data == CB_ADMIN_BROADCAST)
async def on_admin_inline_broadcast(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Запускает рассылку из инлайн-дашборда."""

    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminBroadcastState.waiting_for_text)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            f"📡 <b>РАССЫЛКА</b>\n\nОтправь текст рассылки одним сообщением.\n\n{HINT_BROADCAST}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]
                ]
            ),
            parse_mode="HTML",
        )


async def on_broadcast_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Запускает массовую рассылку всем активным пользователям."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await state.set_state(AdminBroadcastState.waiting_for_text)
    await message.answer(
        f"Отправь текст рассылки одним сообщением.\n\n{HINT_BROADCAST}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]]
        ),
    )


@router.message(AdminBroadcastState.waiting_for_text)
async def on_broadcast_send(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Отправляет массовую рассылку и показывает статистику доставки."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    body = (message.text or "").strip()
    if not body:
        await message.answer("Текст рассылки не может быть пустым. Отправь непустой текст.")
        return

    recipients = await UserService(session=session).get_all_active_users()
    delivered = 0
    failed = 0
    failed_details: list[str] = []
    deactivated_details: list[str] = []
    admin_id = admin_user.id if admin_user is not None else None
    for user in recipients:
        try:
            await bot.send_message(chat_id=user.telegram_id, text=body)
            delivered += 1
            if admin_id is not None:
                session.add(
                    AdminAuditLog(
                        admin_id=admin_id,
                        action="broadcast_delivery_ok",
                        target_type="user",
                        target_id=user.id,
                        details=f"tg_id={user.telegram_id}",
                    )
                )
        except TelegramAPIError as exc:
            failed += 1
            logger.warning("Broadcast delivery failed tg_id=%s: %s", user.telegram_id, exc)
            err = str(exc)
            if admin_id is not None:
                prev_fail_count = int(
                    (
                        await session.execute(
                            select(func.count(AdminAuditLog.id)).where(
                                AdminAuditLog.action == "broadcast_delivery_failed",
                                AdminAuditLog.target_type == "user",
                                AdminAuditLog.target_id == user.id,
                            )
                        )
                    ).scalar_one()
                )
                session.add(
                    AdminAuditLog(
                        admin_id=admin_id,
                        action="broadcast_delivery_failed",
                        target_type="user",
                        target_id=user.id,
                        details=f"tg_id={user.telegram_id};error={err}",
                    )
                )
                if prev_fail_count >= 1:
                    user.is_active = False
                    label = f"@{user.username}" if user.username else str(user.telegram_id)
                    deactivated_details.append(label)
                    session.add(
                        AdminAuditLog(
                            admin_id=admin_id,
                            action="broadcast_auto_deactivate",
                            target_type="user",
                            target_id=user.id,
                            details=f"auto-disabled after repeat failures;tg_id={user.telegram_id}",
                        )
                    )
            if len(failed_details) < 3:
                label = f"@{user.username}" if user.username else str(user.telegram_id)
                failed_details.append(f"- {label}: {err}")


    await state.clear()
    summary_text = f"Рассылка завершена.\nУспешно: {delivered}\nОшибок: {failed}"
    if failed_details:
        summary_text += "\n\nПричины (первые 3):\n" + "\n".join(failed_details)
    if deactivated_details:
        summary_text += "\n\nАвто-удалены из активных (повторная ошибка доставки):\n"
        summary_text += "\n".join(f"- {item}" for item in deactivated_details[:10])
    await message.answer(
        summary_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)]]
        ),
    )
    if admin_user is not None:
        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="broadcast",
            target_type="users",
            details=f"delivered={delivered},failed={failed}",
        )
