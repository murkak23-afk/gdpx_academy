"""Утилиты для форматирования прогресса FSM (Finite State Machine).

Визуализирует текущий шаг в процессе добавления товара продавцом.
"""

from __future__ import annotations


class FSMProgressFormatter:
    """Форматирует визуальный прогресс для шагов FSM добавления товара."""

    # Состояния FSM
    STATE_CATEGORY = 1
    STATE_PHOTO = 2
    STATE_DESCRIPTION = 3  # Номер телефона

    # Иконки и описания для каждого шага
    STEPS = {
        STATE_CATEGORY: {
            "icon": "📂",
            "order": "1️⃣",
            "title": "КАТЕГОРИЯ",
            "descr": "Выбери оператора (МТС, Билайн, и т.д.)",
            "short": "Выбор категории",
        },
        STATE_PHOTO: {
            "icon": "📷",
            "order": "2️⃣",
            "title": "ФОТО",
            "descr": "Загрузи скриншот или архив с симкой",
            "short": "Загрузка фото",
        },
        STATE_DESCRIPTION: {
            "icon": "📞",
            "order": "3️⃣",
            "title": "НОМЕР",
            "descr": "Отправь номер в формате +79999999999",
            "short": "Ввод номера",
        },
    }

    @staticmethod
    def get_progress_bar(current_step: int, total_steps: int = 3) -> str:
        """Возвращает текстовый прогресс-бар.
        
        Пример:
            current_step=1, total=3 → [████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 33%
            current_step=2, total=3 → [████████████░░░░░░░░░░░░░░░░░░░░░░░░░░] 66%
            current_step=3, total=3 → [████████████████████████████████████████] 100%
        """
        filled = current_step
        empty = total_steps - current_step
        percent = int((current_step / total_steps) * 100)

        # Каждый блок = 2 символа
        bar = "█" * (filled * 4) + "░" * (empty * 4)
        return f"[{bar}] {percent}%"

    @staticmethod
    def get_step_visual(current_step: int) -> str:
        """Возвращает кольцо шагов с визуализацией текущего.
        
        Пример:
            current_step=1 → 📍 1️⃣ → ⬜️2️⃣ → ⬜️3️⃣
            current_step=2 → 1️⃣ → 📍 2️⃣ → ⬜️3️⃣
            current_step=3 → 1️⃣ → 2️⃣ → 📍 3️⃣
        """
        steps = []
        for step_num in [1, 2, 3]:
            order = FSMProgressFormatter.STEPS[step_num]["order"]
            
            if step_num < current_step:
                # Готовый шаг - зелёная галочка
                steps.append(f"✅ {order}")
            elif step_num == current_step:
                # Активный шаг - стрелка прямо
                steps.append(f"📍 {order}")
            else:
                # Будущий шаг - пусто
                steps.append(f"⬜️ {order}")
        
        return " → ".join(steps)

    @staticmethod
    def get_step_info(current_step: int) -> dict:
        """Возвращает информацию о текущем шаге."""
        return FSMProgressFormatter.STEPS.get(current_step, {})

    @staticmethod
    def format_fsm_message(
        current_step: int,
        *,
        include_progress_bar: bool = True,
        include_step_visual: bool = True,
        include_description: bool = True,
        full_description: bool = True,
    ) -> str:
        """Форматирует полное сообщение с прогрессом.
        
        Args:
            current_step: текущий номер шага (1, 2, 3)
            include_progress_bar: показать ли прогресс-бар
            include_step_visual: показать ли визуальное кольцо шагов
            include_description: показать ли описание текущего шага
            full_description: подробное описание (True) или краткое (False)
        
        Returns:
            Форматированная строка для отправки в Telegram
        """
        lines = []
        step_info = FSMProgressFormatter.get_step_info(current_step)

        # Заголовок с иконкой и номером шага
        lines.append(f"<b>{step_info['icon']} {step_info['title']}</b>")
        lines.append(f"<i>Шаг {current_step}/3</i>")
        lines.append("")

        # Визуальный прогресс (кольцо с шагами)
        if include_step_visual:
            lines.append(step_info["order"] + " " + FSMProgressFormatter.get_step_visual(current_step))
            lines.append("")

        # Описание текущего шага
        if include_description:
            if full_description:
                lines.append(f"<b>ℹ️ {step_info['short'].upper()}</b>")
                lines.append(step_info["descr"])
            else:
                lines.append(step_info["descr"])
            lines.append("")

        # Прогресс-бар
        if include_progress_bar:
            lines.append(FSMProgressFormatter.get_progress_bar(current_step))
            lines.append("")

        return "\n".join(lines).rstrip()

    @staticmethod
    def format_fsm_quick_message(current_step: int) -> str:
        """Краткое сообщение для QUICK ADD режима (минималист).
        
        Используется для быстрого добавления, когда время критично.
        """
        step_info = FSMProgressFormatter.get_step_info(current_step)
        
        return (
            f"{step_info['icon']} <b>{step_info['short']}</b>\n"
            f"<i>{step_info['descr']}</i>\n"
            f"{FSMProgressFormatter.get_step_visual(current_step)}"
        )

    @staticmethod
    def get_step_emoji_status(current_step: int, target_step: int) -> str:
        """Возвращает эмодзи статуса для конкретного шага.
        
        Args:
            current_step: номер текущего шага
            target_step: номер целевого шага (1, 2 или 3)
        
        Returns:
            ✅ если уже прошли, 📍 если текущий, ⚪ если ещё впереди
        """
        if target_step < current_step:
            return "✅"
        elif target_step == current_step:
            return "📍"
        else:
            return "⚪"
