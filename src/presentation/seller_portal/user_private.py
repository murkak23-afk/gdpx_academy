"""Объединённый роутер для приватных (личных) сообщений пользователя.

Включает хендлеры:
- ``start``      — /start, выбор языка, приветствие
- ``seller``     — профиль, подача материала, история выплат и пр.
- ``withdrawal`` — FSM вывода средств

Роутер ограничен типом чата ``private``, чтобы команды не срабатывали
в групповых чатах модерации.

Почему так устроено?
--------------------
В aiogram 3 фильтры роутера применяются ко ВСЕМ дочерним роутерам.
Значит, достаточно поставить ``F.chat.type == ChatType.PRIVATE`` один раз
здесь — и все вложенные хендлеры автоматически игнорируют групповые чаты.
Это чище, чем дублировать фильтр в каждом хендлере.

Подключение в диспетчере (уже сделано в src/handlers/__init__.py)::

    from src.presentation.seller_portal.user_private import user_private_router
    dp.include_router(user_private_router)
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType

from .academy import router as _academy_router
from .leaderboard.handlers import router as _leaderboard_router
from .registration import router as _registration_router
from .seller import router as _seller_router
from src.presentation.admin_panel.finance.withdrawal import router as _withdrawal_router

# Корневой роутер для всего private-флоу пользователя.
# Фильтр F.chat.type == ChatType.PRIVATE применяется ко всем дочерним роутерам.
user_private_router = Router(name="user-private-router")
user_private_router.message.filter(F.chat.type == ChatType.PRIVATE)
user_private_router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

# Порядок важен: registration — первым, чтобы /start и процесс регистрации перехватывались раньше seller-меню
user_private_router.include_router(_registration_router)
user_private_router.include_router(_academy_router)
user_private_router.include_router(_leaderboard_router)
user_private_router.include_router(_seller_router)
user_private_router.include_router(_withdrawal_router)
