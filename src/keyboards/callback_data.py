"""Типизированные CallbackData — для callback'ов с параметрами.

─────────────────────────────────────────────────────────────────
ПРАВИЛО ИСПОЛЬЗОВАНИЯ
─────────────────────────────────────────────────────────────────
Строковые константы в `callbacks.py` остаются без изменений для
callback'ов БЕЗ параметров (CB_MOD_TAKE, CB_NOOP и т.д.).

Этот файл — ТОЛЬКО для callback'ов с аргументами (ID, номера страниц,
суммы, причины). Они заменяют ручной f"{CB_FOO}:{id}:{page}" и
.split(":") в обработчиках.

─────────────────────────────────────────────────────────────────
ПРАВИЛО МИГРАЦИИ (не ломает старые обработчики)
─────────────────────────────────────────────────────────────────
Миграция — параллельная, не in-place:

1. Добавить новый CallbackData-класс сюда.
2. Обновить keyboard-билдер: заменить f-строку на .pack().
3. Обновить обработчик: заменить F.data.startswith() на .filter().
4. Старый CB_* string-константа в callbacks.py остаётся до полной
   миграции (не удалять до момента когда ни один handler её не использует).

─────────────────────────────────────────────────────────────────
ОГРАНИЧЕНИЕ TELEGRAM
─────────────────────────────────────────────────────────────────
Telegram ограничивает callback_data: 64 байта.
Aiogram сериализует CallbackData как: {prefix}:{field1}:{field2}...
Prefixes здесь — короткие, чтобы оставался запас для int-аргументов.

Самый «тяжёлый» случай: pay_fc:2147483647:2147483647:0 = 32 байта ✓
─────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


# ══════════════════════════════════════════════════════════════════════
# GRADING MATRIX  (handlers/admin_grading.py)
# Было: grade:take:{sub_id}, grade:accept:{sub_id}, ...
# ══════════════════════════════════════════════════════════════════════


class GradeTakeCB(CallbackData, prefix="g_tk"):
    """Взять симку в работу из grading-очереди."""

    submission_id: int


class GradeAcceptCB(CallbackData, prefix="g_ac"):
    """Зачесть симку (ACCEPTED)."""

    submission_id: int


class GradeNotScanCB(CallbackData, prefix="g_ns"):
    """Отказ: не скан."""

    submission_id: int


class GradeBlockedCB(CallbackData, prefix="g_bl"):
    """Отказ: блокировка."""

    submission_id: int


class GradeOtherCB(CallbackData, prefix="g_ot"):
    """Отказ: иное (запускает FSM для ввода причины)."""

    submission_id: int


# ══════════════════════════════════════════════════════════════════════
# MODERATION ACTIONS  (handlers/moderation/ и moderation_flow.py)
# Было: mod:accept:{sub_id}, mod:debit:{sub_id}, mod:reject:{sub_id}
#        mod:rejtpl:{sub_id}:{reason}, mod:rejtpl_back:{sub_id}
#        mod:hold_select:{sub_id}:{hold_key}, mod:hold_skip:{sub_id}
# ══════════════════════════════════════════════════════════════════════


class ModAcceptCB(CallbackData, prefix="m_ac"):
    """Одобрить симку из moderation review."""

    submission_id: int


class ModDebitCB(CallbackData, prefix="m_db"):
    """Открыть меню отклонения симки."""

    submission_id: int


class ModRejectCB(CallbackData, prefix="m_rj"):
    """Финальный отказ с причиной."""

    submission_id: int


class ModRejectTemplateCB(CallbackData, prefix="m_rt"):
    """Выбор шаблона причины отклонения.

    reason — одно из: duplicate | quality | rules | other
    """

    submission_id: int
    reason: str


class ModRejectTemplateBackCB(CallbackData, prefix="m_rb"):
    """Назад из меню шаблонов к карточке."""

    submission_id: int


class ModHoldSelectCB(CallbackData, prefix="m_hs"):
    """Выбор условия холда.

    hold_key — одно из: no_hold | 15m | 30m
    """

    submission_id: int
    hold_key: str


class ModHoldSkipCB(CallbackData, prefix="m_hx"):
    """Пропустить выбор холда."""

    submission_id: int


class ModTakePickCB(CallbackData, prefix="m_tp"):
    """Начать выбор симок определённого продавца для пересылки."""

    user_id: int


class ModReportSubmissionCB(CallbackData, prefix="m_rs"):
    """Открыть детальный отчёт по симке (admin report card)."""

    submission_id: int


# ══════════════════════════════════════════════════════════════════════
# PAYOUT FLOW  (handlers/admin/payouts.py)
# Было: pay:mark:{uid}:{page}, pay:confirm:{uid}:{page},
#        pay:cancel:{uid}:{page}, pay:final_confirm:{uid}:{page},
#        pay:trash:{uid}:{page}, pay:pending_delete:{payout_id}:{page}
#        pay:topup:{page}
# ══════════════════════════════════════════════════════════════════════


class PayMarkCB(CallbackData, prefix="pay_mk"):
    """Инициировать процесс выплаты пользователю."""

    user_id: int
    ledger_page: int = 0


class PayConfirmCB(CallbackData, prefix="pay_cf"):
    """Подтвердить выплату (Этап 1)."""

    user_id: int
    ledger_page: int = 0


class PayCancelCB(CallbackData, prefix="pay_cx"):
    """Отменить выплату и вернуться к ведомости."""

    user_id: int
    ledger_page: int = 0


class PayFinalConfirmCB(CallbackData, prefix="pay_fc"):
    """Финальная отправка чека через CryptoBot (Этап 2)."""

    user_id: int
    ledger_page: int = 0


class PayTrashCB(CallbackData, prefix="pay_tr"):
    """Аннулировать выплату."""

    user_id: int
    ledger_page: int = 0


class PayPendingDeleteCB(CallbackData, prefix="pay_pd"):
    """Удалить конкретный PENDING-payout из списка."""

    payout_id: int
    page: int = 0


class PayTopupCB(CallbackData, prefix="pay_tu"):
    """Открыть форму пополнения резерва CryptoPay."""

    ledger_page: int = 0


class PayTopupCheckCB(CallbackData, prefix="pay_tc"):
    """Проверить статус invoice пополнения.

    invoice_id   — ID invoice из CryptoBot
    ledger_page  — страница ведомости для возврата
    amount_label — строковое представление суммы (для alert)
    """

    invoice_id: int
    ledger_page: int
    amount_label: str


# ══════════════════════════════════════════════════════════════════════
# ADMIN USER MANAGEMENT  (handlers/admin/users.py)
# Было: admin:user_open:{tg_id}, admin:user_ban:{tg_id},
#        admin:user_bal:{tg_id}, admin:user_dm:{tg_id}
# ══════════════════════════════════════════════════════════════════════


class AdminUserOpenCB(CallbackData, prefix="au_op"):
    """Открыть / обновить досье агента."""

    tg_id: int


class AdminUserBanCB(CallbackData, prefix="au_bn"):
    """Переключить бан/разбан агента."""

    tg_id: int


class AdminUserBalanceCB(CallbackData, prefix="au_bl"):
    """Начать ввод корректировки баланса агента."""

    tg_id: int


class AdminUserDmCB(CallbackData, prefix="au_dm"):
    """Начать отправку личного сообщения агенту."""

    tg_id: int


# ══════════════════════════════════════════════════════════════════════
# ADMIN ARCHIVE / SEARCH  (handlers/admin/archive.py)
# Было: admin:restrict:{user_id}, admin:unrestrict:{user_id}
#        admin:report_submission:{sub_id}
#        admin:search_page:{page}:{query}
# ══════════════════════════════════════════════════════════════════════


class AdminRestrictCB(CallbackData, prefix="ar_rs"):
    """Включить ограничение доступа для продавца."""

    user_id: int


class AdminUnrestrictCB(CallbackData, prefix="ar_ur"):
    """Снять ограничение доступа для продавца."""

    user_id: int


# ══════════════════════════════════════════════════════════════════════
# ADMIN STATS  (handlers/admin/stats.py)
# Было: admin:stats_month:{year}:{month}
#        admin:stats_export_month:{year}:{month}
# ══════════════════════════════════════════════════════════════════════


class AdminStatsMonthCB(CallbackData, prefix="as_mo"):
    """Показать статистику за конкретный месяц."""

    year: int
    month: int


class AdminStatsExportMonthCB(CallbackData, prefix="as_ex"):
    """Экспортировать статистику в Excel."""

    year: int
    month: int


# ══════════════════════════════════════════════════════════════════════
# SELLER MATERIALS  (handlers/seller/materials.py)
# Было: seller:mat:card:{sub_id}
# ══════════════════════════════════════════════════════════════════════


class SellerMatCardCB(CallbackData, prefix="sm_cd"):
    """Прямой переход к карточке материала (например, из уведомления)."""

    submission_id: int
