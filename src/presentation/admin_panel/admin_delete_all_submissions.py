from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.submission import Submission
from src.domain.moderation.admin_service import AdminService

router = Router(name="admin-delete-all-submissions")

CONFIRM_CB = "delete_all_submissions_confirm"

from src.presentation.filters.admin import IsOwnerFilter

# Команда для запуска удаления (только для владельца)
@router.message(Command("delete_asim"), IsOwnerFilter())
async def cmd_delete_asim(message: Message, session: AsyncSession):
    count = (await session.execute(select(func.count(Submission.id)))).scalar_one()
    if count == 0:
        await message.answer("✅ В базе нет записей.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Точно удалить ВСЕ сим-карты?", callback_data=CONFIRM_CB)]
        ]
    )
    await message.answer(
        f"⚠️ <b>ВНИМАНИЕ!</b>\nВ базе {count} сим-карт.\n\n"
        "Нажми кнопку ниже для подтверждения.\n\n"
        "Удаление необратимо. Проверь действие перед подтверждением.\n\n",
        parse_mode="HTML",
        reply_markup=kb,
    )

# Обработка подтверждения (только для владельца)
@router.callback_query(F.data == CONFIRM_CB, IsOwnerFilter())
async def cb_confirm_delete_all_submissions(callback: CallbackQuery, session: AsyncSession):
    count = (await session.execute(select(func.count(Submission.id)))).scalar_one()
    from src.core.utils.text_format import edit_message_text_or_caption_safe
    if count == 0:
        await edit_message_text_or_caption_safe(callback.message, "✅ В базе нет записей.")
        return

    await session.execute(delete(Submission))
    await edit_message_text_or_caption_safe(callback.message, f"✅ Удалено {count} сим-карт. База пуста 🚀")
    await callback.answer("Готово!", show_alert=True)
