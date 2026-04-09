from __future__ import annotations
import logging
from html import escape
from decimal import Decimal

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.bill_service import BillingService
from src.services.admin_service import AdminService
from src.services.cryptobot_service import CryptoBotService
from src.services.user_service import UserService
from src.callbacks.finance import FinancePayCD, FinanceTopupCD
from src.keyboards.finance import (
    get_paylist_kb, 
    get_payout_confirm_kb, 
    get_payout_history_kb, 
    get_payout_detail_kb, 
    get_payout_confirm_undo_kb,
    get_finance_stats_kb
)
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.utils.text_format import edit_message_text_or_caption_safe
from src.states.moderation import ModerationStates
from src.database.models.enums import PayoutStatus

router = Router(name="finance-payouts-router")
logger = logging.getLogger(__name__)


@router.message(Command("paylist"))
@router.message(Command("payme"))
@router.message(Command("payouts"))
async def cmd_paylist_start(message: Message, session: AsyncSession):
    """Скрытая команда: список селлеров на выплату."""
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    await _render_paylist(message, session, page=0)


@router.message(Command("payhistory"))
async def cmd_payhistory_start(message: Message, session: AsyncSession):
    """Скрытая команда: история выплат."""
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    await _render_history(message, session, page=0, status_filter="all")


@router.message(Command("paystats"))
async def cmd_paystats_start(message: Message, session: AsyncSession):
    """Скрытая команда: статистика выплат."""
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    await _render_stats(message, session)


@router.callback_query(FinancePayCD.filter(F.action == "list"))
async def cb_paylist_refresh(callback: CallbackQuery, callback_data: FinancePayCD, session: AsyncSession):
    await _render_paylist(callback, session, page=callback_data.page)
    await callback.answer()


@router.callback_query(FinancePayCD.filter(F.action == "history"))
async def cb_payhistory_refresh(callback: CallbackQuery, callback_data: FinancePayCD, session: AsyncSession):
    await _render_history(callback, session, page=callback_data.page, status_filter=callback_data.filter_status)
    await callback.answer()


@router.callback_query(FinancePayCD.filter(F.action == "stats"))
async def cb_paystats_refresh(callback: CallbackQuery, session: AsyncSession):
    await _render_stats(callback, session)
    await callback.answer()


async def _render_paylist(event: Message | CallbackQuery, session: AsyncSession, page: int):
    billing_svc = BillingService(session=session)
    sellers, total = await billing_svc.get_sellers_with_balance(limit=10, offset=page * 10)
    total_debt = sum(s.pending_balance for s in sellers)

    text = (
        f"❖ <b>GDPX // ФИНАНСОВЫЙ РЕЕСТР</b>\n"
        f"{DIVIDER}\n"
        f"🧾 <b>Ожидают выплату:</b> {total} агентов\n"
        f"💰 <b>Общий долг:</b> <code>{total_debt:.2f}</code> USDT\n"
        f"{DIVIDER_LIGHT}\n"
        f"Выберите селлера для инициации транзакции:"
    )

    if not sellers:
        text += "\n\n✨ <b>Все выплаты произведены. Задолженностей нет.</b>"

    kb = get_paylist_kb(sellers, page, total)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")


async def _render_history(event: Message | CallbackQuery, session: AsyncSession, page: int, status_filter: str):
    billing_svc = BillingService(session=session)
    payouts, total = await billing_svc.get_payout_history(status=status_filter, limit=10, offset=page*10)

    text = (
        f"❖ <b>GDPX // ИСТОРИЯ ВЫПЛАТ</b>\n"
        f"{DIVIDER}\n"
        f"🔍 <b>Фильтр:</b> <code>{status_filter.upper()}</code>\n"
        f"📊 <b>Всего записей:</b> {total}\n"
        f"{DIVIDER_LIGHT}\n"
    )

    if not payouts:
        text += "📭 <i>История пуста.</i>"
    else:
        for p in payouts:
            icon = "🟢" if p.status == PayoutStatus.PAID else "⏳" if p.status == PayoutStatus.PENDING else "🔴"
            date_str = p.created_at.strftime("%d.%m %H:%M")
            text += f"{icon} <b>#{p.id}</b> | <code>{p.amount}</code> USDT | {date_str}\n"
        
        text += f"{DIVIDER}\n<i>Для просмотра деталей используйте поиск или CSV-экспорт.</i>"

    kb = get_payout_history_kb(payouts, page, total, status_filter)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")


async def _render_stats(event: Message | CallbackQuery, session: AsyncSession):
    billing_svc = BillingService(session=session)
    stats = await billing_svc.get_finance_stats()

    text = (
        f"❖ <b>GDPX // ФИНАНСОВЫЙ ДАШБОРД</b>\n"
        f"{DIVIDER}\n"
        f"📅 <b>СЕГОДНЯ:</b>\n"
        f" ├ Выплат: <code>{stats['today']['count']}</code> шт.\n"
        f" └ Сумма: <code>{stats['today']['sum']:.2f}</code> USDT\n\n"
        f"📅 <b>НЕДЕЛЯ:</b>\n"
        f" ├ Выплат: <code>{stats['week']['count']}</code> шт.\n"
        f" └ Сумма: <code>{stats['week']['sum']:.2f}</code> USDT\n\n"
        f"📅 <b>МЕСЯЦ:</b>\n"
        f" ├ Выплат: <code>{stats['month']['count']}</code> шт.\n"
        f" └ Сумма: <code>{stats['month']['sum']:.2f}</code> USDT\n"
        f"{DIVIDER_LIGHT}\n"
        f"🏆 <b>ТОП ПОЛУЧАТЕЛЕЙ (ALL TIME):</b>\n"
    )

    for i, s in enumerate(stats['top_sellers'], 1):
        text += f" {i}. {escape(s['name'])} — <code>{s['amount']:.2f}</code> USDT\n"

    kb = get_finance_stats_kb()

    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(FinancePayCD.filter(F.action == "user_detail"))
async def cb_paylist_user_detail(callback: CallbackQuery, callback_data: FinancePayCD, session: AsyncSession):
    billing_svc = BillingService(session=session)
    seller = await billing_svc.get_seller_balance_info(callback_data.user_id)

    if not seller or seller.pending_balance <= 0:
        await callback.answer("🔴 Баланс селлера пуст.", show_alert=True)
        return await _render_paylist(callback, session, callback_data.page)

    name = f"@{seller.username}" if seller.username else f"ID: {seller.telegram_id}"

    text = (
        f"❖ <b>GDPX // ИНИЦИАЦИЯ ВЫПЛАТЫ</b>\n"
        f"{DIVIDER}\n"
        f"👤 <b>Агент:</b> {escape(name)}\n"
        f"💳 <b>Реквизиты:</b> <code>{escape(seller.payout_details or 'USDT CryptoBot')}</code>\n"
        f"{DIVIDER_LIGHT}\n"
        f"💰 <b>СУММА К ВЫПЛАТЕ:</b> <code>{seller.pending_balance}</code> USDT\n\n"
        f"⚠️ <i>После подтверждения средства будут списаны с баланса приложения в CryptoBot.</i>"
    )

    await edit_message_text_or_caption_safe(
        callback.message, text, 
        reply_markup=get_payout_confirm_kb(seller.id, callback_data.page), 
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(FinancePayCD.filter(F.action == "hist_detail"))
async def cb_payout_detail(callback: CallbackQuery, callback_data: FinancePayCD, session: AsyncSession):
    billing_svc = BillingService(session=session)
    payout = await billing_svc.get_payout_by_id(callback_data.payout_id)
    if not payout:
        return await callback.answer("Выплата не найдена", show_alert=True)

    user_svc = UserService(session=session)
    seller = await user_svc.get_by_id(payout.user_id)
    name = f"@{seller.username}" if seller and seller.username else f"ID:{payout.user_id}"

    status_emoji = "🟢" if payout.status == PayoutStatus.PAID else "⏳" if payout.status == PayoutStatus.PENDING else "🔴"
    
    text = (
        f"❖ <b>ТРАНЗАКЦИЯ #{payout.id}</b>\n"
        f"{DIVIDER}\n"
        f"👤 <b>Селлер:</b> {escape(name)}\n"
        f"💰 <b>Сумма:</b> <code>{payout.amount}</code> USDT\n"
        f"📅 <b>Дата:</b> <code>{payout.created_at.strftime('%d.%m.%Y %H:%M')}</code>\n"
        f"{DIVIDER_LIGHT}\n"
        f"📉 <b>СТАТУС:</b> {status_emoji} <b>{payout.status.value.upper()}</b>\n"
    )

    if payout.crypto_check_url:
        text += f"🔗 <b>Чек:</b> <a href='{payout.crypto_check_url}'>Открыть в CryptoBot</a>\n"
    
    if payout.status == PayoutStatus.CANCELLED and payout.cancelled_at:
        text += f"🕒 <b>Отменено:</b> {payout.cancelled_at.strftime('%d.%m.%Y %H:%M')}\n"

    await edit_message_text_or_caption_safe(
        callback.message, text, 
        reply_markup=get_payout_detail_kb(payout.id, payout.status, callback_data.page, callback_data.filter_status), 
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(FinancePayCD.filter(F.action == "undo_ask"))
async def cb_payout_undo_ask(callback: CallbackQuery, callback_data: FinancePayCD):
    text = (
        f"⚠️ <b>ОТМЕНА ВЫПЛАТЫ #{callback_data.payout_id}</b>\n"
        f"{DIVIDER}\n"
        f"Вы уверены, что хотите отменить эту выплату?\n\n"
        f"• Статус станет <code>CANCELLED</code>\n"
        f"• Средства <b>ВЕРНУТСЯ</b> на баланс селлера"
    )
    await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_payout_confirm_undo_kb(callback_data.payout_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(FinancePayCD.filter(F.action == "undo_confirm"))
async def cb_payout_undo_confirm(callback: CallbackQuery, callback_data: FinancePayCD, session: AsyncSession):
    user_svc = UserService(session=session)
    admin = await user_svc.get_by_telegram_id(callback.from_user.id)
    
    billing_svc = BillingService(session=session)
    success, msg = await billing_svc.cancel_pending_payout(callback_data.payout_id, admin.id)
    await session.commit()
    
    await callback.answer(msg, show_alert=True)
    await _render_history(callback, session, page=0, status_filter="cancelled")


@router.callback_query(FinancePayCD.filter(F.action == "confirm"))
async def cb_payout_confirm(callback: CallbackQuery, callback_data: FinancePayCD, session: AsyncSession, bot: Bot):
    """ПОДТВЕРЖДЕНИЕ: Списание баланса и выдача чека."""
    from src.services.user_service import UserService
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    
    billing_svc = BillingService(session=session)
    seller = await billing_svc.get_seller_balance_info(callback_data.user_id)
    
    if not seller or seller.pending_balance <= 0:
        return await callback.answer("🔴 Ошибка: баланс уже пуст.", show_alert=True)

    amount_to_pay = seller.pending_balance
    name = f"@{seller.username}" if seller.username else f"ID:{seller.telegram_id}"

    await edit_message_text_or_caption_safe(callback.message, "⏳ <b>Формирование транзакции...</b>\n<i>Связь с Crypto Pay API...</i>", parse_mode="HTML")

    crypto_svc = CryptoBotService()
    try:
        check = await crypto_svc.create_usdt_check(amount_to_pay, comment=f"Выплата {name}")
    except Exception as e:
        logger.error(f"CryptoPay Error: {e}")
        text = f"🔴 <b>Ошибка Crypto Pay API:</b>\n<code>{e}</code>\n<i>Транзакция отменена. Баланс не списан.</i>"
        back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❮ ВЕРНУТЬСЯ К РЕЕСТРУ", callback_data=FinancePayCD(action="list", page=callback_data.page).pack())]])
        await edit_message_text_or_caption_safe(callback.message, text, reply_markup=back_kb, parse_mode="HTML")
        return

    payout_record = await billing_svc.execute_crypto_payout(
        user_id=seller.id, 
        admin_id=admin.id, 
        amount=amount_to_pay,
        check_id=check.check_id,
        check_url=check.check_url
    )
    await session.commit()

    if not payout_record:
        return await callback.answer("🔴 Системная ошибка БД.", show_alert=True)

    receipt_text = (
        f"❖ <b>GDPX // ФИНАНСЫ</b>\n"
        f"{DIVIDER}\n"
        f"✅ <b>ВАМ ПОСТУПИЛА ВЫПЛАТА!</b>\n\n"
        f"💰 <b>Сумма:</b> <code>{amount_to_pay}</code> USDT\n"
        f"🧾 <b>Транзакция:</b> #{payout_record.id}\n"
        f"{DIVIDER_LIGHT}\n"
        f"👉 <a href='{check.check_url}'><b>ПОЛУЧИТЬ USDT В CRYPTO BOT</b></a>\n\n"
        f"<i>Спасибо за отличную работу! Ждем новых активов.</i>"
    )
    try:
        await bot.send_message(chat_id=seller.telegram_id, text=receipt_text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        pass

    success_text = (
        f"✅ <b>ВЫПЛАТА УСПЕШНА</b>\n"
        f"{DIVIDER}\n"
        f"Средства (<code>{amount_to_pay}</code> USDT) списаны с баланса {escape(name)}.\n"
        f"Квитанция и чек CryptoBot отправлены агенту.\n\n"
        f"🔗 <b><a href='{check.check_url}'>Ссылка на чек (Резервная)</a></b>"
    )
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❮ ВЕРНУТЬСЯ К РЕЕСТРУ", callback_data=FinancePayCD(action="list", page=callback_data.page).pack())]])
    await edit_message_text_or_caption_safe(callback.message, success_text, reply_markup=back_kb, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer("✅ Транзакция проведена")


@router.message(Command("topup"))
@router.message(Command("deposit"))
async def cmd_topup_start(message: Message, session: AsyncSession):
    """Скрытая команда: создание счета на пополнение баланса выплат."""
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return
    await start_topup_process(message, session)


async def start_topup_process(event: Message | CallbackQuery, session: AsyncSession):
    """Централизованная функция входа в процесс пополнения баланса (из команды или кнопки)."""
    from src.keyboards.finance import get_topup_kb
    
    text = (
        f"❖ <b>ПОПОЛНЕНИЕ БАЛАНСА ВЫПЛАТ</b>\n"
        f"{DIVIDER}\n"
        f"Выберите сумму для генерации счета на оплату.\n"
        f"<i>Средства поступят на кошелек приложения в CryptoBot.</i>"
    )
    
    kb = get_topup_kb()
    
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await edit_message_text_or_caption_safe(event.message, text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(FinanceTopupCD.filter())
async def cb_topup_create_invoice(callback: CallbackQuery, callback_data: FinanceTopupCD, session: AsyncSession):
    amount = Decimal(str(callback_data.amount))
    await callback.message.edit_text("⏳ <b>Генерация счета...</b>", parse_mode="HTML")
    
    crypto_svc = CryptoBotService()
    try:
        invoice = await crypto_svc.create_topup_invoice(
            amount=amount,
            description=f"Top-up by Admin ID {callback.from_user.id}"
        )
    except Exception as e:
        logger.error(f"Topup Error: {e}")
        return await callback.message.edit_text(f"🔴 <b>Ошибка API:</b>\n<code>{e}</code>", parse_mode="HTML")

    text = (
        f"❖ <b>СЧЁТ СФОРМИРОВАН</b>\n"
        f"{DIVIDER}\n"
        f"💰 <b>Сумма к оплате:</b> <code>{amount}</code> USDT\n"
        f"🧾 <b>Invoice ID:</b> <code>{invoice.invoice_id}</code>\n"
        f"{DIVIDER_LIGHT}\n"
        f"👉 <a href='{invoice.invoice_url}'><b>ОПЛАТИТЬ ЧЕРЕЗ CRYPTO BOT</b></a>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❮ НАЗАД", callback_data="mod_back_dash")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data == "topup_custom")
async def cb_topup_custom_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ModerationStates.waiting_for_topup_amount)
    await callback.message.edit_text("✍️ <b>Введите сумму пополнения в USDT:</b>\n<i>(Например: 15.5 или 100)</i>", parse_mode="HTML")
    await callback.answer()


@router.message(ModerationStates.waiting_for_topup_amount, F.text)
async def process_topup_custom_amount(message: Message, state: FSMContext, session: AsyncSession):
    raw_text = message.text.replace(",", ".").strip()
    try:
        amount = Decimal(raw_text)
        if amount <= 0: raise ValueError
    except Exception:
        return await message.answer("❌ <b>Ошибка:</b> Введите положительное число.")

    await state.clear()
    await message.answer("⏳ <b>Генерация счета...</b>", parse_mode="HTML")
    
    crypto_svc = CryptoBotService()
    try:
        invoice = await crypto_svc.create_topup_invoice(amount=amount, description=f"Top-up by Admin ID {message.from_user.id}")
        text = (
            f"❖ <b>СЧЁТ СФОРМИРОВАН</b>\n"
            f"{DIVIDER}\n"
            f"💰 <b>Сумма к оплате:</b> <code>{amount}</code> USDT\n"
            f"🧾 <b>Invoice ID:</b> <code>{invoice.invoice_id}</code>\n"
            f"{DIVIDER_LIGHT}\n"
            f"👉 <a href='{invoice.invoice_url}'><b>ОПЛАТИТЬ ЧЕРЕЗ CRYPTO BOT</b></a>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❮ НАЗАД", callback_data="mod_back_dash")]])
        await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await message.answer(f"🔴 <b>Ошибка API:</b>\n<code>{e}</code>", parse_mode="HTML")
