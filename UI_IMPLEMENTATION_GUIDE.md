# 🛠️ QUICK START GUIDE: Реализация Top-5 Улучшений

Практические примеры кода для быстрого внедрения самых важных фич.

---

## 🎯 TOP-5 УЛУЧШЕНИЙ ДЛЯ НЕМЕДЛЕННОЙ РЕАЛИЗАЦИИ

### 1️⃣ БОТ COMMANDS MENU (30 мин, ~5 строк кода)

**Что добавлять:** Правильное меню команд в Telegram при нажатии "/"

#### Решение:

**Файл:** `src/core/bot.py`

```python
# В конце функции create_bot():
async def setup_commands():
    bot = create_bot()  # уже существует
    commands = [
        BotCommand(command="start", description="🚀 Начать"),
        BotCommand(command="profile", description="👤 Мой профиль"),
        BotCommand(command="sell", description="📤 Сдать eSIM"),
        BotCommand(command="stats", description="📊 Статистика"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    
    # Для обычных пользователей
    await bot.set_my_commands(
        commands=commands,
        scope=BotCommandScopeDefault()
    )
    
    # Для админов (расширенное меню)
    admin_commands = commands + [
        BotCommand(command="queue", description="📜 Очередь (admin)"),
        BotCommand(command="payouts", description="💰 Выплаты (admin)"),
        BotCommand(command="stats_adv", description="📈 Расширенная статистика (admin)"),
    ]
    
    await bot.set_my_commands(
        commands=admin_commands,
        scope=BotCommandScopeAllAdministrators()
    )
    
    logger.info("Bot commands setup completed")

# Вызова в run_application() после create_bot()
bot = create_bot()
await setup_commands()
```

#### Быстрый тест:
```bash
# В Telegram, нажми "/" и увидишь menu
# Должны показаться команды с описаниями
```

---

### 2️⃣ INLINE QUERY ДЛЯ ПОИСКА (1 день, ~100 строк кода)

**Что добавлять:** Быстрый поиск товара прямо в любом чате без выхода из диалога

#### Решение:

**Новый файл:** `src/handlers/inline_search.py`

```python
from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.submission import Submission
from src.services import SubmissionService
from src.utils.submission_format import submission_status_emoji_line

router = Router(name="inline-search-router")
logger = logging.getLogger(__name__)


@router.inline_query()
async def on_inline_search(query: InlineQuery, session: AsyncSession) -> None:
    """
    Поиск товаров по номеру (последние цифры) в реальном времени.
    Админ типит "@bot 234" в любом чате → видит результаты.
    """
    
    search_query = query.query.strip()
    
    # Если ничего не введено, не показывай результаты
    if not search_query or len(search_query) < 4:
        await query.answer(
            results=[],
            cache_time=0,
            is_personal=True,
        )
        return
    
    # Поиск по номеру (последние цифры или полный номер)
    submission_service = SubmissionService(session=session)
    
    try:
        # Если ввёл полный номер +7...
        if search_query.startswith("+7") and len(search_query) == 12:
            submissions = await submission_service.search_by_phone_exact(search_query)
        else:
            # Иначе ищем по последним цифрам
            digits = "".join(filter(str.isdigit, search_query))
            if len(digits) < 4:
                await query.answer(results=[], cache_time=0, is_personal=True)
                return
            
            submissions = await submission_service.search_by_phone_partial(digits, limit=5)
    
    except Exception as e:
        logger.exception(f"Inline search error: {e}")
        await query.answer(results=[], cache_time=0)
        return
    
    # Форматировать результаты
    results = []
    for idx, submission in enumerate(submissions, start=1):
        text = format_inline_result(submission)
        
        article = InlineQueryResultArticle(
            id=f"sub_{submission.id}_{idx}",
            title=f"#{submission.id} {submission.description_text or '---'}",
            description=f"{submission.category.title if submission.category else 'unknown'} | {submission.status.value}",
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode="HTML",
            ),
        )
        results.append(article)
    
    await query.answer(results=results, cache_time=0, is_personal=True)


def format_inline_result(submission: Submission) -> str:
    """Форматировать компактный результат для inline."""
    phone = submission.description_text or "---"
    category = submission.category.title if submission.category else "unknown"
    
    return (
        f"<b>Товар #{submission.id}</b>\n"
        f"📱 <code>{phone}</code>\n"
        f"Категория: {category}\n"
        f"Статус: {submission_status_emoji_line(submission)}\n"
        f"Опубликовано: {submission.created_at:%H:%M:%S}"
    )
```

**Добавить импорт в** `src/handlers/__init__.py`:
```python
from src.handlers.inline_search import router as inline_search_router

# В create_dispatcher():
dispatcher.include_router(inline_search_router)
```

#### Тест:
```bash
# В любом чате напиши:
@your_bot 234

# Должны показаться товары с номерами заканчивающимися на 234
```

---

### 3️⃣ QUICK ADD TEMPLATE (1 день, ~50 строк кода)

**Что добавлять:** Быстрое добавления товара (одна кнопка вместо 3 шагов)

#### Решение:

**Добавить в** `src/handlers/seller.py`:

```python
from src.keyboards.callbacks import CB_QUICK_ADD_CATEGORY

# Новая функция
def quick_add_categories_keyboard(categories: list) -> InlineKeyboardMarkup:
    """Быстро добавить товар — выбор категории в одну кнопку."""
    rows = []
    
    # Топ 5 популярных категорий
    popular = sorted(categories, key=lambda c: c.active_submissions_count, reverse=True)[:5]
    
    for cat in popular:
        rows.append([
            InlineKeyboardButton(
                text=f"📱 {cat.title}",
                callback_data=f"{CB_QUICK_ADD_CATEGORY}:{cat.id}"
            )
        ])
    
    rows.append([
        InlineKeyboardButton(
            text="📋 Все категории",
            callback_data=f"{CB_QUICK_ADD_CATEGORY}:all"
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Обработчик
@router.message(F.text == "🚀 Быстро добавить")
async def on_quick_add_start(message: Message, session: AsyncSession) -> None:
    """Начало быстрого добавления товара."""
    if message.from_user is None:
        return
    
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди /start")
        return
    
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await message.answer("Категории недоступны. Попробуй позже.")
        return
    
    await message.answer(
        "<b>🚀 Быстро добавить товар</b>\n\n"
        "Выбери категорию (популярные):\n",
        reply_markup=quick_add_categories_keyboard(categories),
    )


# Обновить Callback
@router.callback_query(F.data.startswith(f"{CB_QUICK_ADD_CATEGORY}:"))
async def on_quick_add_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Быстрое добавление после выбора категории."""
    if callback.from_user is None or callback.data is None:
        return
    
    category_id = callback.data.split(":")[1]
    
    if category_id == "all":
        # Показать все категории (как раньше)
        # ... существующий код
        pass
    else:
        # Быстро перейти к загрузке фото
        await state.set_state(SubmissionState.waiting_for_photo)
        await state.update_data(category_id=int(category_id))
        
        await callback.message.edit_text(
            "<b>Шаг 2/3: Загрузи фото или архив</b>\n\n"
            "Подпись: <code>+79999999999</code> для автозачета",
            reply_markup=_seller_fsm_cancel_keyboard(),
        )
```

**Добавить callback в** `src/keyboards/callbacks.py`:
```python
CB_QUICK_ADD_CATEGORY = "qa_cat"
```

**Добавить кнопку в** `seller_main_menu_keyboard` в `src/keyboards/reply.py`:
```python
rows.insert(0, [KeyboardButton(text="🚀 Быстро добавить")])
```

---

### 4️⃣ PROGRESS INDICATOR FOR FSM (1 день, ~30 строк кода)

**Что добавлять:** Визуальный прогресс в FSM (шаг 1/3, 2/3, 3/3)

#### Решение:

**Новый файл:** `src/utils/fsm_progress.py`

```python
from src.states.submission_state import SubmissionState

def get_fsm_progress(current_state: str) -> str:
    """Вернуть визуальный прогресс FSM."""
    
    progress_map = {
        SubmissionState.waiting_for_category.state: (1, 3, "Выбор категории"),
        SubmissionState.waiting_for_photo.state: (2, 3, "Загрузка фото"),
        SubmissionState.waiting_for_description.state: (3, 3, "Ввод номера"),
    }
    
    step, total, label = progress_map.get(
        current_state,
        (0, 0, "Неизвестно")
    )
    
    # Визуализация:
    # [████░░░░░] 2/3
    filled = int((step / total) * 10)
    bar = "█" * filled + "░" * (10 - filled)
    
    return (
        f"\n\n<b>Прогресс:</b> [{bar}] {step}/{total}\n"
        f"<i>{label}</i>"
    )


def add_progress_to_message(text: str, current_state: str) -> str:
    """Добавить прогресс к сообщению FSM."""
    progress = get_fsm_progress(current_state)
    return text + progress
```

**Использовать в** `src/handlers/seller.py`:

```python
from src.utils.fsm_progress import add_progress_to_message

# Заменить все места, где отправляем FSM сообщения:

# Было:
await message.answer("Выбери категорию...")

# Стало:
state_data = await state.get_data()
current_state = await state.get_state()
text = "Выбери категорию..."
text = add_progress_to_message(text, current_state)
await message.answer(text, ...)
```

---

### 5️⃣ QUEUE FILTER & SEARCH (2 дня, ~150 строк кода)

**Что добавлять:** Встроенный фильтр для очереди товаров

#### Решение:

**Добавить в** `src/states/moderation_state.py`:

```python
from aiogram.fsm.state import State, StatesGroup

class AdminQueueFilterState(StatesGroup):
    """FSM для фильтрации очереди."""
    waiting_for_filter_choice = State()
    waiting_for_search_query = State()
```

**Новые функции в** `src/handlers/admin.py`:

```python
from aiogram.fsm.context import FSMContext
from src.states.moderation_state import AdminQueueFilterState

def _queue_filter_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора типа фильтра."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 По номеру", callback_data="qf_phone"),
            InlineKeyboardButton(text="📁 По категории", callback_data="qf_category"),
        ],
        [InlineKeyboardButton(text="⏱️ По времени", callback_data="qf_time")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="qf_cancel")],
    ])


async def _apply_queue_filter(
    session: AsyncSession,
    filter_type: str,
    filter_value: str,
) -> tuple[str, int]:
    """Применить фильтр и вернуть (текст, всего товаров)."""
    
    svc = SubmissionService(session=session)
    
    if filter_type == "phone":
        digits = "".join(filter(str.isdigit, filter_value))
        submissions = await svc.search_pending_by_phone(digits)
    
    elif filter_type == "category":
        submissions = await svc.list_pending_by_category_title(filter_value)
    
    elif filter_type == "time":
        # Фильтр по времени (по последним N минут)
        minutes = int(filter_value) if filter_value.isdigit() else 30
        submissions = await svc.list_pending_recent(minutes=minutes)
    
    else:
        submissions = []
    
    text = f"Результаты поиска: {len(submissions)} товаров\n\n"
    for sub in submissions[:10]:  # Показать топ-10
        text += f"• #{sub.id} {sub.description_text or '---'} ({sub.created_at:%H:%M})\n"
    
    if len(submissions) > 10:
        text += f"\n... и ещё {len(submissions) - 10} товаров"
    
    return text, len(submissions)


# Обработчик
@router.callback_query(F.data == "queue_filter")
async def on_queue_filter_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начно фильтрации очереди."""
    await state.set_state(AdminQueueFilterState.waiting_for_filter_choice)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "Выбери тип фильтра:",
            reply_markup=_queue_filter_keyboard(),
        )


@router.callback_query(F.data.startswith("qf_"))
async def on_queue_filter_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор типа фильтра."""
    if callback.data == "qf_cancel":
        await callback.answer()
        await state.clear()
        return
    
    filter_type = callback.data.split("_")[1]
    
    if filter_type == "phone":
        prompt = "Введи номер или последние цифры (4+):"
    elif filter_type == "category":
        prompt = "Введи название категории (например: МТС Салон):"
    elif filter_type == "time":
        prompt = "Введи количество минут (30, 60, 120):"
    else:
        return
    
    await state.set_state(AdminQueueFilterState.waiting_for_search_query)
    await state.update_data(filter_type=filter_type)
    
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(prompt)


@router.message(AdminQueueFilterState.waiting_for_search_query, F.text)
async def on_queue_filter_query(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Применить фильтр и показать результаты."""
    if message.text is None:
        return
    
    data = await state.get_data()
    filter_type = data.get("filter_type")
    
    text, count = await _apply_queue_filter(session, filter_type, message.text.strip())
    
    await state.clear()
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Новый поиск", callback_data="queue_filter")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=CB_ADMIN_QUEUE)],
        ]),
    )
```

---

## 📋 CHECKLIST ВНЕДРЕНИЯ

```
[ ] 1. Bot Commands Menu
  [ ] Добавить setup_commands() в bot.py
  [ ] Вызвать в run_application()
  [ ] Тестировать "/" в Telegram
  
[ ] 2. Inline Query Search
  [ ] Создать handlers/inline_search.py
  [ ] Добавить в dispatcher
  [ ] Реализовать search_by_phone_* в SubmissionService
  [ ] Тестировать "@bot 234"
  
[ ] 3. Quick Add Template
  [ ] Создать quick_add_categories_keyboard()
  [ ] Обработку on_quick_add_start
  [ ] Добавить CB_QUICK_ADD_CATEGORY в callbacks
  [ ] Добавить кнопку в reply меню
  
[ ] 4. Progress Indicator
  [ ] Создать fsm_progress.py
  [ ] Добавить прогресс ко всем FSM сообщениям
  [ ] Тестировать визуал
  
[ ] 5. Queue Filter
  [ ] Создать AdminQueueFilterState в states
  [ ] Реализовать фильтр функции
  [ ] Добавить обработчики callback'ов
  [ ] Реализовать методы поиска в SubmissionService
```

---

## ⏰ ПРИМЕРНЫЙ РАСЧЕТ ВРЕМЕНИ

| Фича | Prep | Dev | Test | Total |
|------|------|-----|------|-------|
| Bot Commands | 5 мин | 15 мин | 10 мин | **30 мин** |
| Inline Query | 30 мин | 3 ч | 30 мин | **4 ч** |
| Quick Add | 15 мин | 2 ч | 30 мин | **2.5 ч** |
| Progress | 15 мин | 2 ч | 30 мин | **2.5 ч** |
| Queue Filter | 30 мин | 4 ч | 1 ч | **5.5 ч** |

**ИТОГО: ~15 часов (~2 дня непрерывной работы)**

Рекомендуется делать одну за раз с полным тестированием и интеграцией.

---

## 🎯 НАЧНИ С ЭТОГО

```bash
# День 1, утро:
# 30 мин на Bot Commands Menu
# Убедись, что "/" меню работает

# День 1, после обеда:
# 2.5 часа на Quick Add Template
# Протестируй новую кнопку "🚀 Быстро добавить"

# День 2, утро:
# 4 часа на Inline Query Search
# Тестируй "@bot 234" в разных чатах

# День 2, после обеда:
# Refactoring и доп polish
```

---

**Успехов в реализации! 🚀**
