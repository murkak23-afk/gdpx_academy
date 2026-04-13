from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.presentation.common.factory import AdminGradeCD, AdminQueueCD, AdminSellerQueueCD
from src.core.logger import logger
from src.database.models.enums import SubmissionStatus
from .keyboards import get_mod_inspector_kb, get_mod_reasons_kb
from src.domain.moderation.moderation_service import ModerationService
from src.domain.users.user_service import UserService
from src.domain.moderation.moderation_state import ModerationStates
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT

router = Router(name="moderation-inspector-router")

async def _render_next_item(bot: Bot, chat_id: int, session: AsyncSession, state: FSMContext):
    """Автоматическая выдача следующей карточки из ЛИЧНОЙ очереди админа."""
    from src.core.config import get_settings
    settings = get_settings()
    
    if getattr(settings, "moderation_suspended", False):
        text = (
            f"⚠️ <b>РАБОТА ПРИОСТАНОВЛЕНА</b>\n"
            f"{DIVIDER}\n"
            f"Владелец временно ограничил работу модераторов.\n\n"
            f"<i>Пожалуйста, подождите или свяжитесь с руководством.</i>"
        )
        await bot.send_message(chat_id, text, parse_mode="HTML")
        await state.clear()
        return

    mod_svc = ModerationService(session=session)
    from src.domain.users.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(chat_id)

    item = await mod_svc.get_next_my_item(admin.id)
    remaining = await mod_svc.get_my_active_items(admin.id)

    if not item:
        text = (
            f"✨ <b>ИНСПЕКТОР ОСТАНОВЛЕН</b>\n"
            f"{DIVIDER}\n"
            f"В вашем личном списке «В работе» больше нет активов.\n\n"
            f"<i>Вернитесь в дашборд или возьмите новую партию из очереди.</i>"
        )
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 ПЕРЕЙТИ К ОЧЕРЕДИ", callback_data="mod_q:start")],
            [InlineKeyboardButton(text="❮ В ДАШБОРД", callback_data="mod_back_dash")]
        ])
        await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
        await state.clear()
        return

    user_svc = UserService(session=session)
    seller = await user_svc.get_by_id(item.user_id)
    wait_min = int((datetime.now(timezone.utc) - item.created_at).total_seconds() / 60)
    sla = "🔴" if wait_min > 15 else "🟡" if wait_min > 8 else "🟢"

    phone = item.phone_normalized
    ident = f"...{phone[-4:]}" if phone else f"#{item.id}"

    caption = (
        f"❖ <b>ИНСПЕКТОР // {sla} {ident}</b>\n{DIVIDER}\n"
        f"👤 <b>Селлер:</b> @{seller.username or 'ID:'+str(seller.id)}\n"
        f"🗂 <b>Кластер:</b> <code>{item.category.title}</code>\n"
        f"💰 <b>Ставка:</b> <code>{item.fixed_payout_rate}</code> USDT\n"
        f"{DIVIDER_LIGHT}\n"
        f"⌛ <b>Ожидание:</b> <code>{wait_min}м</code>\n"
    )

    await bot.send_photo(
        chat_id=chat_id,
        photo=item.telegram_file_id,
        caption=caption,
        reply_markup=get_mod_inspector_kb(item.id, remaining),
        parse_mode="HTML"
    )
    await state.set_state(ModerationStates.conveyor_active)

@router.callback_query(AdminQueueCD.filter(F.action == "next"))
async def mod_next_card(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot):
    """Переход к следующей карточке (из очереди или списка 'в работе')."""
    if callback.message.photo:
        await callback.message.delete()
    await _render_next_item(bot, callback.from_user.id, session, state)


@router.callback_query(F.data == "mod_continue_work")
async def handle_continue(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    """Продолжить работу с сохраненными активами."""
    await callback.message.delete()
    await _render_next_item(bot, callback.from_user.id, session, state)

@router.callback_query(AdminSellerQueueCD.filter(F.action.startswith("take_")))
async def handle_take_batch(callback: CallbackQuery, callback_data: AdminSellerQueueCD, session: AsyncSession, state: FSMContext, bot: Bot):
    """Берет пачку активов и запускает инспектор."""
    from src.domain.users.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)

    count_map = {"take_all": 999, "take_5": 5, "take_10": 10, "take_20": 20}
    count = count_map.get(callback_data.action, 5)

    mod_svc = ModerationService(session=session)
    actual_taken = await mod_svc.take_items_to_work(admin.id, count, user_id=callback_data.user_id)
    await session.commit()

    if actual_taken > 0:
        await callback.message.delete()
        await _render_next_item(bot, callback.from_user.id, session, state)
        await callback.answer(f"✅ Взято в работу: {actual_taken}")
    else:
        await callback.answer("🔴 Ошибка: Активы уже забрали!", show_alert=True)

@router.callback_query(AdminGradeCD.filter(F.action == "accept"))
async def mod_approve(callback: CallbackQuery, callback_data: AdminGradeCD, session: AsyncSession, state: FSMContext, bot: Bot):
    """Мгновенный ЗАЧЕТ актива + плашка отката."""
    try:
        user_svc = UserService(session=session)
        admin = await user_svc.get_by_telegram_id(callback.from_user.id)

        mod_svc = ModerationService(session=session)
        success = await mod_svc.finalize_submission(callback_data.item_id, SubmissionStatus.ACCEPTED, bot=bot, admin_id=admin.id)
        if not success:
            await callback.answer("⚠️ Ошибка: актив уже обработан или не найден", show_alert=True)
            return
            
        logger.info(f"Admin {callback.from_user.id} ACCEPTED sub {callback_data.item_id}")
        
        # Показываем плашку успеха
        await _show_success_with_undo(bot, callback.message.chat.id, callback.message.message_id, callback_data.item_id, "ЗАЧЁТ")
        
        # И сразу присылаем НОВЫМ сообщением следующую карточку
        await _render_next_item(bot, callback.from_user.id, session, state)
    except Exception as e:
        logger.exception(f"Error in mod_approve: {e}")
        await callback.answer("❌ Ошибка при одобрении", show_alert=True)


# =====================================================================
# НИЖЕ ВОССТАНОВЛЕННЫЕ ФУНКЦИИ ДЛЯ ОТКАЗОВ И ПАУЗЫ
# =====================================================================

@router.callback_query(AdminGradeCD.filter(F.action.in_(["not_scan", "reject", "block"])))
async def mod_defect_menu(callback: CallbackQuery, callback_data: AdminGradeCD):
    """Переход в меню выбора причин брака/блока."""
    await callback.message.edit_reply_markup(
        reply_markup=get_mod_reasons_kb(callback_data.item_id, callback_data.action)
    )

@router.callback_query(AdminGradeCD.filter(F.action == "reason"))
async def mod_finalize_defect_cd(callback: CallbackQuery, callback_data: AdminGradeCD, session: AsyncSession, state: FSMContext, bot: Bot):
    """Завершение с выбранной причиной через CallbackData (БЕЗОПАСНО)."""
    try:
        # Формат val: "TYPE|REASON"
        if "|" not in callback_data.val:
            return await callback.answer("❌ Ошибка формата данных", show_alert=True)
            
        type_key, reason = callback_data.val.split("|", 1)
        item_id = callback_data.item_id
        
        # Если выбрано 'CUSTOM', переходим к вводу
        if reason == "CUSTOM":
            await state.update_data(mod_item_id=item_id, mod_mode=type_key)
            await state.set_state(ModerationStates.waiting_for_custom_comment)
            await callback.message.answer("✍️ <b>Введите ваш комментарий для селлера:</b>\n<i>(Причина будет 'Другое')</i>", parse_mode="HTML")
            await callback.answer()
            return

        # Иначе финализируем
        status_map = {
            "not_scan": SubmissionStatus.NOT_A_SCAN, 
            "reject": SubmissionStatus.REJECTED, 
            "block": SubmissionStatus.BLOCKED
        }

        if type_key not in status_map:
            return await callback.answer("❌ Ошибка типа статуса", show_alert=True)

        # Восстанавливаем возможные двоеточия (если мы их заменяли на | при упаковке)
        real_reason = reason.replace("|", ":")
        
        user_svc = UserService(session=session)
        admin = await user_svc.get_by_telegram_id(callback.from_user.id)

        mod_svc = ModerationService(session=session)
        success = await mod_svc.finalize_submission(item_id, status_map[type_key], reason=real_reason, bot=bot, admin_id=admin.id)
        
        if not success:
            return await callback.answer("⚠️ Ошибка: актив уже обработан", show_alert=True)
            
        # Плашка успеха и следующий
        action_label = "БРАК" if type_key == "reject" else "НЕ СКАН" if type_key == "not_scan" else "БЛОК"
        await _show_success_with_undo(bot, callback.message.chat.id, callback.message.message_id, item_id, action_label)
        await _render_next_item(bot, callback.from_user.id, session, state)
        
    except Exception as e:
        logger.exception(f"Error in mod_finalize_defect_cd: {e}")
        await callback.answer("❌ Ошибка при финализации", show_alert=True)

@router.callback_query(F.data == "mod_pause")
async def mod_pause(callback: CallbackQuery, state: FSMContext):
    """Приостановка работы (возврат в меню)."""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("⏸ <b>Конвейер приостановлен.</b>\nВаши взятые активы сохранены в разделе «В работе».", parse_mode="HTML")

@router.message(ModerationStates.waiting_for_custom_comment, F.text)
async def process_custom_comment(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """Прием и сохранение кастомного комментария."""
    data = await state.get_data()
    item_id = int(data['mod_item_id'])
    mode = data['mod_mode']

    status_map = {
        "not_scan": SubmissionStatus.NOT_A_SCAN,
        "reject": SubmissionStatus.REJECTED,
        "block": SubmissionStatus.BLOCKED
    }

    user_svc = UserService(session=session)
    admin = await user_svc.get_by_telegram_id(message.from_user.id)

    mod_svc = ModerationService(session=session)
    await mod_svc.finalize_submission(item_id, status_map[mode], reason="Другое", comment=message.text, bot=bot, admin_id=admin.id)
    await session.commit()

    await message.answer(f"✅ Актив #{item_id} отклонен с вашим комментарием.")
    await _render_next_item(bot, message.from_user.id, session, state)

@router.callback_query(AdminGradeCD.filter(F.action == "cancel_defect"))
async def mod_cancel_defect(callback: CallbackQuery, callback_data: AdminGradeCD, session: AsyncSession):
    """Возврат от выбора причины обратно к главной клавиатуре инспектора (Зачёт/Брак/Блок)."""
    from src.domain.users.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    
    mod_svc = ModerationService(session=session)
    remaining = await mod_svc.get_my_active_items(admin.id)
    
    # Возвращаем исходную клавиатуру карточки
    await callback.message.edit_reply_markup(
        reply_markup=get_mod_inspector_kb(callback_data.item_id, remaining)
    )

async def _show_success_with_undo(bot: Bot, chat_id: int, message_id: int, item_id: int, action_text: str):
    """Превращает проверенную карточку в плашку успеха с кнопкой отката."""
    from .keyboards import get_undo_kb
    text = f"✅ <b>Карточка #{item_id} обработана: {action_text}</b>"
    
    try:
        await bot.edit_message_caption(
            chat_id=chat_id, 
            message_id=message_id, 
            caption=text, 
            reply_markup=get_undo_kb(item_id), 
            parse_mode="HTML"
        )
    except Exception:
        pass
        
    # Запускаем таймер на удаление кнопки
    asyncio.create_task(_remove_undo_button(bot, chat_id, message_id, text))


async def _remove_undo_button(bot: Bot, chat_id: int, message_id: int, text: str):
    """Через 60 секунд убирает кнопку отката."""
    await asyncio.sleep(60)
    try:
        await bot.edit_message_caption(
            chat_id=chat_id, 
            message_id=message_id, 
            caption=text + "\n<i>(Время отката истекло)</i>", 
            reply_markup=None, 
            parse_mode="HTML"
        )
    except Exception:
        pass    

@router.callback_query(AdminGradeCD.filter(F.action == "undo"))
async def mod_undo_action(callback: CallbackQuery, callback_data: AdminGradeCD, session: AsyncSession, state: FSMContext, bot: Bot):
    """Обработчик нажатия на кнопку ОТКАТ."""
    from src.domain.users.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    
    mod_svc = ModerationService(session=session)
    success, msg = await mod_svc.undo_submission_action(callback_data.item_id, admin.id)
    
    if success:
        await session.commit()
        await callback.answer("✅ Откат успешен! Оцени актив заново.", show_alert=True)
        from src.database.models.submission import Submission
        item = await mod_svc._session.get(Submission, callback_data.item_id)
        seller = await UserService(session=session).get_by_id(item.user_id)
        
        wait_min = int((datetime.now(timezone.utc) - item.created_at).total_seconds() / 60)
        sla = "🔴" if wait_min > 15 else "🟡" if wait_min > 8 else "🟢"
        phone = item.phone_normalized
        ident = f"...{phone[-4:]}" if phone else f"#{item.id}"

        # Формируем текст с пометкой, что это откаченная заявка
        caption = (
            f"❖ <b>ИНСПЕКТОР // {sla} {ident}</b>\n{DIVIDER}\n"
            f"👤 <b>Селлер:</b> @{seller.username or 'ID:'+str(seller.id)}\n"
            f"🗂 <b>Кластер:</b> <code>{item.category.title}</code>\n"
            f"💰 <b>Ставка:</b> <code>{item.fixed_payout_rate}</code> USDT\n"
            f"{DIVIDER_LIGHT}\n"
            f"⚠️ <b>ВНИМАНИЕ: ДЕЙСТВИЕ ОТКАТИЛОСЬ</b>\n"
            f"<i>Вы отменили прошлое решение. Выберите правильный статус ниже:</i>"
        )
        
        remaining = await mod_svc.get_my_active_items(admin.id)
        
        # Превращаем сообщение обратно в карточку инспектора!
        try:
            await bot.edit_message_caption(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                caption=caption,
                reply_markup=get_mod_inspector_kb(item.id, remaining),
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await callback.answer(msg, show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None) # Убираем кнопку, если время вышло по БД