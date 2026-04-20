from __future__ import annotations
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.presentation.common.factory import SellerMenuCD, NavCD, SellerDynamicsCD
from src.core.utils.message_manager import MessageManager
from src.core.utils.ui_builder import GDPXRenderer
from src.database.models.submission import Submission
from src.domain.users.user_service import UserService
from .keyboards import get_sim_dynamics_kb

router = Router(name="seller-dynamics-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

ITEMS_PER_PAGE = 20

# Хранилище активных задач обновления {tg_id: task}
_dynamics_tasks: dict[int, asyncio.Task] = {}

async def _get_dynamics_data(session: AsyncSession, db_user_id: int, page: int):
    """Вспомогательная функция получения данных для динамики."""
    from sqlalchemy import func
    # 1. Общее количество
    count_stmt = select(func.count()).select_from(Submission).where(Submission.user_id == db_user_id)
    total_items = (await session.execute(count_stmt)).scalar() or 0

    # 2. Сводка по всем статусам (независимо от страницы)
    stats_stmt = select(Submission.status, func.count()).where(Submission.user_id == db_user_id).group_by(Submission.status)
    stats_res = await session.execute(stats_stmt)
    total_counts = {s: c for s, c in stats_res.all()}

    # 3. Элементы текущей страницы
    stmt = (
        select(Submission)
        .where(Submission.user_id == db_user_id)
        .order_by(Submission.id.desc())
        .offset(page * ITEMS_PER_PAGE)
        .limit(ITEMS_PER_PAGE)
    )
    res = await session.execute(stmt)
    submissions = res.scalars().all()
    
    return total_items, total_counts, submissions

async def _dynamics_update_loop(db_user_id: int, tg_id: int, chat_id: int, bot: Bot, ui: MessageManager, session_factory, current_page: int):
    """Цикл фонового обновления состояния eSIM."""
    try:
        for _ in range(60): 
            await asyncio.sleep(5)
            
            async with session_factory() as session:
                total_items, total_counts, submissions = await _get_dynamics_data(session, db_user_id, current_page)
                
                if not submissions and current_page == 0:
                    continue

                text = _renderer.render_sim_dynamics(submissions, total_counts)
                
                from aiogram.types import User, Chat
                class FakeEvent:
                    def __init__(self, uid, cid):
                        self.from_user = User(id=uid, is_bot=False, first_name="User")
                        self.chat = Chat(id=cid, type="private")
                
                event = FakeEvent(tg_id, chat_id)
                await ui.display(
                    event=event, 
                    text=text, 
                    reply_markup=await get_sim_dynamics_kb(current_page, total_items, ITEMS_PER_PAGE)
                )

    except asyncio.CancelledError:
        logger.debug(f"Dynamics task cancelled for user {tg_id}")
    except Exception as e:
        logger.error(f"Error in dynamics loop for {tg_id}: {e}")
    finally:
        _dynamics_tasks.pop(tg_id, None)

@router.callback_query(SellerMenuCD.filter(F.action == "dynamics"))
@router.callback_query(SellerDynamicsCD.filter(F.action == "view"))
async def cb_seller_dynamics(callback: CallbackQuery, callback_data: SellerMenuCD | SellerDynamicsCD, session: AsyncSession, ui: MessageManager, bot: Bot):
    """Вход в раздел состояния eSIM."""
    tg_id = callback.from_user.id
    chat_id = callback.message.chat.id
    current_page = getattr(callback_data, "page", 0)

    # ПОЛУЧАЕМ DB_USER_ID
    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if not user:
        return await callback.answer("❌ Ошибка профиля")
    
    db_user_id = user.id

    if tg_id in _dynamics_tasks:
        _dynamics_tasks[tg_id].cancel()

    total_items, total_counts, submissions = await _get_dynamics_data(session, db_user_id, current_page)
    
    text = _renderer.render_sim_dynamics(submissions, total_counts)
    await ui.display(
        event=callback, 
        text=text, 
        reply_markup=await get_sim_dynamics_kb(current_page, total_items, ITEMS_PER_PAGE)
    )
    await callback.answer()

    from src.database.session import SessionFactory
    _dynamics_tasks[tg_id] = asyncio.create_task(
        _dynamics_update_loop(db_user_id, tg_id, chat_id, bot, ui, SessionFactory, current_page)
    )

@router.callback_query(F.data.startswith("sel_dyn_pg:"))
async def cb_dynamics_pagination(callback: CallbackQuery, session: AsyncSession, ui: MessageManager, bot: Bot):
    """Обработка переключения страниц."""
    page = int(callback.data.split(":")[1])
    cd = SellerDynamicsCD(action="view", page=page)
    await cb_seller_dynamics(callback, cd, session, ui, bot)

@router.callback_query(NavCD.filter(F.to == "menu"))
async def cb_exit_dynamics(callback: CallbackQuery):
    """Остановка задачи при выходе в меню."""
    tg_id = callback.from_user.id
    if tg_id in _dynamics_tasks:
        _dynamics_tasks[tg_id].cancel()
