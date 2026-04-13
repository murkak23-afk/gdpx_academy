"""Silver Sakura — Стили и цветовые акценты."""

from __future__ import annotations

from src.presentation.common.constants import *


def style_primary(text: str) -> str:
    """Главные действия."""
    return f"✨ {text}"

def style_danger(text: str) -> str:
    """Опасные действия."""
    return f"🛑 {text}"

def style_oriental(text: str, emoji: str = EMOJI_PAGODA) -> str:
    """Восточный акцент."""
    return f"{emoji} {text}"

def style_prio(text: str) -> str:
    """Приоритетные элементы."""
    return f"{EMOJI_LANTERN} {text}"
