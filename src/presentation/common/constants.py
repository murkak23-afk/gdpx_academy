"""Silver Sakura — Константы и Эмодзи."""

from __future__ import annotations

# Основные эмодзи стиля Silver Sakura
EMOJI_APPROVE = "✅"
EMOJI_REJECT = "❌"
EMOJI_BACK = "❮"
EMOJI_UNDO = "↩️"
EMOJI_REFRESH = "🔄"
EMOJI_MODERATION = "⚖️"
EMOJI_FINANCE = "💎"
EMOJI_ASSETS = "🧧"
EMOJI_STATS = "📈"
EMOJI_KNOWLEDGE = "📜"
EMOJI_SUPPORT = "🛡"
EMOJI_PROFILE = "🀄️"
EMOJI_SEARCH = "🔍"
EMOJI_BOX = "📦"
EMOJI_PAGODA = "🏯"
EMOJI_LANTERN = "🏮"
EMOJI_DANGER = "⚠️"
EMOJI_DELETE = "🗑"
EMOJI_BADGE_STAR = "⭐"
EMOJI_BADGE_MEDAL = "🏅"
EMOJI_BADGE_FIRE = "🔥"
EMOJI_BADGE_CROWN = "👑"

# Заголовки разделов
HEADER_MAIN = "❖ <b>GDPX // TERMINAL</b>"
HEADER_ADMIN_MAIN = "⚙️ <b>MODERATOR // CONTROL</b>"
HEADER_OWNER_MAIN = "🛡 <b>FOUNDER // STRATEGY</b>"
HEADER_PROFILE = "👤 <b>AGENT // IDENTITY</b>"
HEADER_HISTORY = "📜 <b>ASSETS // HISTORY</b>"
HEADER_FINANCE = "💎 <b>FINANCE // CLEARING</b>"
HEADER_QUEUE = "⚖️ <b>QUEUE // MODERATION</b>"
HEADER_CATCON = "🛠 <b>CLUSTER // CONFIG</b>"
HEADER_STATS = "📈 <b>ANALYTICS // REPORT</b>"
HEADER_LEADERBOARD = "🏆 <b>VANGUARD // LEADERBOARD</b>"

# Визуальные разделители
DIVIDER = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"
DIVIDER_LIGHT = "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
PREFIX_ITEM = "  ├"
PREFIX_LAST = "  └"

STATUS_EMOJI: dict[str, str] = {
    "accepted": "🟢",
    "approved": "🟢",
    "paid": "🟢",
    "rejected": "🔴",
    "cancelled": "▫️",
    "blocked": "🚫",
    "not_a_scan": "📦",
    "pending": "⏳",
    "in_review": "🟠",
}

# Текстовые константы
TEXT_BACK = f"{EMOJI_BACK} Назад"
TEXT_CANCEL = f"{EMOJI_REJECT} Отмена"
TEXT_CLOSE = f"{EMOJI_REJECT} Закрыть"
