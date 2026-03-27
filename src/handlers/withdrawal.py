from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import AdminService
from src.services.withdrawal import InsufficientBalanceError, WithdrawalService

logger = logging.getLogger(__name__)

router = Router(name="withdrawal-router")
_withdrawal = WithdrawalService()


def _parse_amount(text: str) -> Decimal:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError("Укажи сумму: /withdraw 10.5")
    return Decimal(parts[1].strip().replace(",", "."))


@router.message(F.text.startswith("/withdraw"))
async def withdraw_handler(message: Message, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).can_access_payout_finance(message.from_user.id):
        await message.answer("Команда доступна только администратору выплат (или главному администратору).")
        return
    try:
        amount = _parse_amount(message.text)
    except (InvalidOperation, ValueError) as exc:
        await message.answer(str(exc))
        return

    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    amount_str = format(amount, "f")
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=f"wdr_confirm:{amount_str}")

    await message.answer(
        f"Вывести {amount_str} USDT?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("wdr_confirm:"))
async def confirm_handler(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.data is None or callback.from_user is None:
        await callback.answer()
        return

    if not await AdminService(session=session).can_access_payout_finance(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    try:
        raw = callback.data.split(":", 1)[1]
        amount = Decimal(raw)
    except (InvalidOperation, IndexError, ValueError):
        await callback.answer("Некорректная сумма", show_alert=True)
        return

    if amount <= 0:
        await callback.answer("Сумма должна быть > 0", show_alert=True)
        return

    try:
        result = await _withdrawal.execute_withdrawal(amount)
    except InsufficientBalanceError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except (RuntimeError, ValueError) as exc:
        logger.exception("Ошибка вывода: %s", exc)
        await callback.answer("Не удалось создать чек. Попробуй позже.", show_alert=True)
        return

    await callback.answer("Готово")
    if callback.message is not None:
        await callback.message.answer(f"✅ Чек создан:\n{result.check_url}")
