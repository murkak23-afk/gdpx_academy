from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.admin_service import AdminService
from src.database.session import SessionFactory
from src.database.models.submission import Submission
from sqlalchemy import delete, func, select

router = Router(name="admin-delete-all-submissions")

CONFIRM_CB = "delete_all_submissions_confirm"

# Команда для запуска удаления (только для chief_admin)
@router.message(Command("delete_asim"))
async def cmd_delete_asim(message: Message, session: AsyncSession):
    if not await AdminService(session).can_manage_payouts(message.from_user.id):
        await message.answer("❌ Нет прав. Только для главного администратора.")
        return

    count = (await session.execute(select(func.count(Submission.id)))).scalar_one()
    if count == 0:
        await message.answer("✅ В базе нихуя нет 👀")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Точно удалить ВСЕ сим-карты?", callback_data=CONFIRM_CB)]
        ]
    )
    await message.answer(
        f"⚠️ <b>ВНИМАНИЕ!</b>\nВ базе {count} сим-карт.\n\n"
        "Нажми кнопку ниже для подтверждения.\n\n"
        "Жги их нахуй, <b>МУРА!🔥</b>!\n\n",
        parse_mode="HTML",
        reply_markup=kb,
    )

# Обработка подтверждения
@router.callback_query(F.data == CONFIRM_CB)
async def cb_confirm_delete_all_submissions(callback: CallbackQuery, session: AsyncSession):
    if not await AdminService(session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    count = (await session.execute(select(func.count(Submission.id)))).scalar_one()
    if count == 0:
        await callback.message.edit_text("✅ В базе нихуя нет 👀")
        return

    await session.execute(delete(Submission))
    await session.commit()
    await callback.message.edit_text(f"✅ Удалено {count} сим-карт. База пуста 🚀")
    await callback.answer("Готово!", show_alert=True)
