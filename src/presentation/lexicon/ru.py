"""Лексикон — единый центр управления текстами бота.

Все строки интерфейса хранятся здесь.  Хендлеры импортируют константы;
текст не дублируется и не «зашит» в логику.

──────────────────────────────────────────────────
Соглашения об именах:
──────────────────────────────────────────────────
  ERR_*    — сообщения об ошибках
  OK_*     — подтверждения успешных действий
  ASK_*    — вопросы / приглашения к вводу
  INFO_*   — информационные экраны
  BTN_*    — подписи кнопок (дubro duplicated with keyboards/ where needed)
  WARN_*   — предупреждения

Строки с плейсхолдерами: используй .format(**kwargs) или f-string
только если нужны динамические данные.

Пример использования в хендлере:
    from src.presentation.lexicon.ru import Lex
    await message.answer(Lex.ERR_DB_UNAVAILABLE, parse_mode="HTML")
    await message.answer(Lex.OK_PRIZE_SAVED.format(state=state_word), parse_mode="HTML")
"""

from __future__ import annotations


class Lex:
    """Namespace-класс: все строки как атрибуты класса (без экземпляра).

    IDE-автодополнение работает «из коробки».
    """

    # ══════════════════════════════════════════════════════════════════════
    # СИСТЕМНЫЕ / ОШИБКИ
    # ══════════════════════════════════════════════════════════════════════

    ERR_DB_UNAVAILABLE = (
        "✖ <b>[SYSTEM ERROR] // LINK LOST</b>\n"
        "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
        "Ядро базы данных не отвечает. Протокол синхронизации нарушен.\n\n"
        "<i>Статус: Попытка переподключения...</i>"
    )
    # Backward compatibility alias for older imports.
    EERR_DB_UNAVAILABLE = ERR_DB_UNAVAILABLE

    ERR_NO_RIGHTS = (
        "✖ <b>ACCESS DENIED // SECURITY</b>\n"
        "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
        "В доступе отказано. Требуемый уровень: <code>ARCHITECT</code>.\n"
        "<i>Ваш цифровой след зафиксирован в логах безопасности.</i>"
    )
    ERR_NO_RIGHTS_ALERT = "[ ROOT ACCESS DENIED ]"

    ERR_SESSION_EXPIRED = "✖ <b>SESSION EXPIRED</b>\nТокен сессии истек. Инициируйте операцию заново."
    ERR_AMOUNT_CORRUPT = "✖ <b>CALIBRATION ERROR</b>\nСбой калибрации: неверный формат суммы."
    ERR_WITHDRAW_FAILED = "✖ <b>GATEWAY REJECTED</b>\nCryptoBot отклонил запрос. Повторите цикл позже."

    # ══════════════════════════════════════════════════════════════════════
    # РЕГИСТРАЦИЯ / ОНБОРДИНГ
    # ══════════════════════════════════════════════════════════════════════

    ASK_LANGUAGE = "❖ <b>GDPX // INITIALIZATION</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\nУстановите языковой пакет интерфейса:"

    # {requirements} подставляется в шаблон, чтобы правила можно было изменить отдельно
    ASK_PSEUDONYM = (
        "🔖 <b>IDENTITY // INITIALIZATION</b>\n"
        "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
        "Установите ваш позывной для глобального реестра.\n\n"
        "▫ <b>Формат:</b> 2–32 символа [A-Z, 0-9, _, -]\n"
        "▫ <b>Статус:</b> <i>Изменение невозможно после фиксации</i>\n\n"
        "📡 <code>Ожидание ввода...</code>"
    )

    ASK_LANGUAGE_ONLY_BUTTON = "Пожалуйста, выбери язык кнопкой ниже."

    WARN_PSEUDONYM_INVALID = (
        "⚠️ <b>SYNTAX ERROR // IDENTITY</b>\n"
        "Допускаются только буквы, цифры, <code>_</code> и <code>-</code> (от 2 до 32 символов).\n"
        "Введите корректный ID:"
    )
    WARN_PSEUDONYM_TAKEN = "⚠️ <b>COLLISION ERROR</b>\nИдентификатор уже используется. Введите уникальный ID:"

    # ══════════════════════════════════════════════════════════════════════
    # ВЫВОД СРЕДСТВ (/withdraw)
    # ══════════════════════════════════════════════════════════════════════

    ERR_WITHDRAW_USAGE = "✖ <b>SYNTAX ERROR</b>\nФормат ввода: <code>/withdraw 10.5</code>"
    ERR_WITHDRAW_ZERO = "✖ <b>LIQUIDITY ERROR</b>\nСумма вывода должна быть больше нуля."

    # {amount} — строковое представление Decimal
    ASK_WITHDRAW_CONFIRM = "💠 <b>CONFIRMATION // CLEARING</b>\nПодтвердить транзакцию: <b>{amount} USDT</b>?"

    OK_WITHDRAW_DONE = "📡 <code>PROCESSING TRANSACTION...</code>"
    # {check_url} — ссылка CryptoBot
    OK_WITHDRAW_CHECK = (
        "💠 <b>CLEARING // SUCCESS</b>\n"
        "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
        "Транзакция верифицирована. Активы переведены в ликвидный чек.\n\n"
        "🔗 <b>LINK:</b> {check_url}\n\n"
        "<i>[!] Чек действителен в течение 24 часов.</i>"
    )

    OK_CANCEL = "🌑 <code>OPERATION ABORTED</code>"

    # ══════════════════════════════════════════════════════════════════════
    # КНОПКИ (дублируются в keyboards.inline, чтобы хендлеры могли взять из lexicon)
    # ══════════════════════════════════════════════════════════════════════

    BTN_CONFIRM = "❖ ACCEPT"
    BTN_CANCEL = "✖ ABORT"
    BTN_BACK = "◂ RETURN"
    BTN_REFRESH = "↻ RELOAD"
    BTN_WDR_CONFIRM = "❖ EXECUTE CLEARING"

    BTN_TERMINATE_SESSION = "⊗ TERMINATE SESSION"
    BTN_TERMINATE_CONFIRM = "◾ CONFIRM CLEANUP"

    # ══════════════════════════════════════════════════════════════════════
    # PANIC BUTTON / SESSION CLEANUP
    # ══════════════════════════════════════════════════════════════════════

    INFO_SESSION_TERMINATE_CONFIRM = (
        "🚨 <b>PROTOCOL // CLEANUP</b>\n"
        "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
        "Внимание. Инициирован полный сброс сессии.\n"
        "Все логи терминала будут безвозвратно стерты.\n\n"
        "⚠️ <b>ОПЕРАЦИЯ НЕОБРАТИМА.</b> Исполнить?"
    )

    INFO_SESSION_TERMINATED = "🌑 <code>[ SESSION TERMINATED // LOGS WIPED ]</code>"

    # ══════════════════════════════════════════════════════════════════════
    # ПРАВА / МОДЕРАЦИЯ (общие)
    # ══════════════════════════════════════════════════════════════════════

    WARN_ACCESS_DENIED_ALERT = "[ ROOT ACCESS DENIED ]"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Support  —  seller/info.py → on_seller_menu_support
    # ══════════════════════════════════════════════════════════════════════

    class Support:
        """SUPPORT CENTER — экран поддержки продавца."""

        HEADER = "🛡 <b>SUPPORT // CENTER</b>"
        DIVIDER = "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▰▰▰▰▰▰▰▰▰"
        STATUS = "📡 [🟢 <b>ONLINE</b>] ── <i>Ping: 15m.</i>"

        # Плейсхолдеры: {divider} {founder} {helper_1} {helper_2} {architect} {status}
        BODY = (
            "{header}\n"
            "{divider}\n"
            "🌑 <b>FOUNDER</b> ── {founder}\n"
            "  └─<i>Ресурсы / Глобальный выкуп</i>\n\n"
            "🛡 <b>SUPPORT</b> ── {helper_1} | {helper_2}\n"
            "  └─<i>Наставление / Прием eSIM</i>\n\n"
            "⚙️ <b>ARCHITECT</b> ── {architect}\n"
            "  └─<i>Технические вопросы / Ядро</i>\n"
            "{divider}\n"
            "{status}\n"
        )

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Sub  —  seller/submission.py
    # ══════════════════════════════════════════════════════════════════════

    class Sub:
        """Тексты FSM-потока загрузки материалов (submission)."""

        ERR_RESTRICTED = (
            "✖ <b>ACCESS RESTRICTED</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "Ваш доступ временно ограничен. Требуется верификация личности."
        )
        # {until} — datetime строкой
        ERR_TIMEOUT = (
            "✖ <b>FLOOD TIMEOUT</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\nОбнаружены дубликаты. Тайм-аут до: <code>{until}</code>"
        )
        ERR_NO_CATEGORY = "✖ <b>CATEGORY ERROR</b>\nСначала выберите кластер (подтип оператора)."
        ERR_NO_QUOTA = "✖ <b>QUOTA ERROR</b>\nНа сегодня в этом кластере лимит выгрузок не назначен."
        # {limit} — int, дневной лимит
        ERR_QUOTA_EXCEEDED = "✖ <b>LIMIT EXCEEDED</b>\nДневная квота кластера исчерпана: <code>{limit}</code>."

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Pay  —  handlers/admin/payouts.py
    # ══════════════════════════════════════════════════════════════════════

    class Pay:
        """Тексты раздела выплат (admin/payouts.py)."""

        LEDGER_HEADER = "💸 <b>LEDGER // PAYOUTS</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
        LEDGER_EMPTY = "🌑 <b>EMPTY</b>\nПользователи с ожидающими выплатами отсутствуют."

        HISTORY_HEADER = "📜 <b>HISTORY // ARCHIVE</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
        HISTORY_EMPTY = "🌑 <b>EMPTY</b>"

        TRASH_HEADER = "🗑 <b>RECYCLE BIN // PAYOUTS</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
        TRASH_EMPTY = "🌑 <b>EMPTY</b>"

        PENDING_HEADER = "⚙️ <b>CONTROL // PAYOUTS</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
        PENDING_EMPTY = "🔴 <b>NO PENDING DATA</b>"

        # Кнопки навигации ведомости
        BTN_TOPUP = "💳 TOPUP USDT"
        BTN_HISTORY = "📜 HISTORY"
        BTN_TRASH = "🗑 RECYCLE BIN"
        BTN_PENDING_MANAGE = "⚙️ MANAGE PAYOUT"
        BTN_TO_LEDGER = "💸 TO LEDGER"

        ERR_NO_EXPORT_DATA = "✖ <b>EXPORT ERROR</b>\nНет данных для выгрузки."
        ERR_NO_RIGHTS = "✖ <b>ACCESS DENIED</b>"

        # Alert-сообщения (show_alert=True)
        ALERT_NO_RIGHTS = "[ ACCESS DENIED ]"
        ALERT_BAD_DATA = "[ CORRUPT DATA ]"
        ALERT_USER_NOT_FOUND = "[ AGENT NOT FOUND ]"
        ALERT_NO_PENDING = "[ NO PENDING ASSETS ]"
        ALERT_INVOICE_BAD_ID = "[ INVALID INVOICE ID ]"
        ALERT_INVOICE_NOT_PAID = "[ NOT PAID ]"
        ALERT_SESSION_LOST = "[ SESSION LOST ]"
        ALERT_INVOICE_FAILED = "[ GATEWAY ERROR ]"
        # {amount} {asset}
        ALERT_TOPUP_OK = "✅ <b>TOPUP SUCCESS:</b> +{amount} {asset}"

        PAID_CANCEL_ALERT = "ABORTED"

        # {username} {total_accepted} {rejected} {total_amount}
        CONFIRM_STEP1 = (
            "💠 <b>EMISSION // STAGE 01</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "▫ <b>AGENT:</b> <code>{username}</code>\n"
            "▫ <b>CYCLE:</b> ACTIVE\n\n"
            "📊 <b>ASSETS SUMMARY:</b>\n"
            "  ├ 🟢 <b>VALID:</b>  <code>{total_accepted} шт.</code>\n"
            "  └ 🔴 <b>REJECT:</b> <code>{rejected} шт.</code>\n\n"
            "💰 <b>CLEARING:</b> <code>{total_amount} USDT</code>\n"
            "<i>[!] Coefficients applied.</i>\n\n"
            "<b>❖ EXECUTE TRANSACTION?</b>"
        )
        # {total_amount} {username} {balance_line} {warning_line}
        CONFIRM_STEP2 = (
            "💠 <b>EMISSION // STAGE 02</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "📡 <code>WAITING FOR ROOT SIGNATURE...</code>\n\n"
            "▫ <b>VOLUME:</b> <code>{total_amount} USDT</code>\n"
            "▫ <b>TARGET:</b> <code>{username}</code>\n\n"
            "⚙️ <b>STATUS:</b>\n"
            "{balance_line}\n"
            "{warning_line}\n\n"
            "⚠️ <i>[CRITICAL] IRREVERSIBLE ACTION.</i>\n"
            "<b>❖ FIX HASH?</b>"
        )
        CONFIRM_STEP2_BALANCE_OK = "  └ 🟢 <b>[SECURE]:</b> RESERVE CONFIRMED."
        CONFIRM_STEP2_BALANCE_LOW = "  └ 🔴 <b>[FAIL]:</b> LIQUIDITY DEPLETED."

        CONFIRM_STEP2_BALANCE_LINE = "  ├ <b>LIQUIDITY:</b> <code>{balance} USDT</code>"
        CONFIRM_STEP2_BALANCE_ERR = "  └ 🔴 <b>[GATEWAY FAIL]:</b> ({error})"

        TOPUP_ASK = (
            "💸 <b>APP // TOPUP</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "Введите объем транша в USDT.\n"
            "📡 <code>Waiting for input...</code>"
        )
        TOPUP_RESERVE_HDR = "❖ <b>GDPX // CRYPTOPAY</b>"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Mailing  —  handlers/admin/mailing.py
    # ══════════════════════════════════════════════════════════════════════

    class Mailing:
        """Тексты модуля рассылки (admin/mailing.py)."""

        ASK_INPUT = (
            "📡 <b>UPLINK // BROADCAST</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "Отправьте тело сообщения.\n"
            "Поддерживается: Текст, Фото + Текст.\n\n"
            "{hint}"
        )
        ERR_EMPTY = "✖ <b>EMPTY PAYLOAD</b>"

        # {has_photo} "да"/"нет", {preview_body}
        PREVIEW = (
            "📋 <b>PREVIEW // BROADCAST</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "▫ <b>PHOTO:</b> {has_photo}\n"
            "▫ <b>BODY:</b>\n"
            "<blockquote>{preview_body}</blockquote>\n\n"
            "<b>❖ START BROADCAST?</b>"
        )
        PREVIEW_PHOTO_YES = "YES"
        PREVIEW_PHOTO_NO = "NO"

        # {ok} {blocked} {failed}
        REPORT = (
            "📡 <b>BROADCAST // COMPLETE</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "✔️ DELIVERED: <b>{ok}</b>\n"
            "🚫 BLOCKED: <b>{blocked}</b>\n"
            "⚠️ FAILED: <b>{failed}</b>"
        )
        ERR_NO_RIGHTS = "✖ <b>ACCESS DENIED</b>"
        ALERT_NO_RIGHTS = "[ ACCESS DENIED ]"

        BTN_LAUNCH = "◉ LAUNCH"
        BTN_CANCEL = "✖ ABORT"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Stats  —  handlers/admin/stats.py
    # ══════════════════════════════════════════════════════════════════════

    class Stats:
        """Тексты раздела статистики (admin/stats.py)."""

        # {month:02d} {year}
        HEADER = "📊 <b>LOGS // SIM STATS {month:02d}.{year}</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
        TABLE_HEADER = "<code>DAY | IN | ✔️ | ❌ | 🚫 | ⛔</code>"
        TOTAL_LABEL = "<b>MONTHLY SUMMARY</b>"

        # {total_incoming} {total_accepted} {total_failed} {rejected} {blocked} {not_scan}
        TOTAL_ROW = (
            "▫ INCOMING SIM: <b>{total_incoming}</b>\n"
            "▫ ACCEPTED: <b>{total_accepted}</b>\n"
            "▫ FAILED: <b>{total_failed}</b>\n"
            "<i>(REJECTED={rejected}, BLOCKED={blocked}, NOT_SCAN={not_scan})</i>"
        )
        BTN_EXPORT = "🌸 EXPORT EXCEL"
        BTN_RESET = "🗑 WIPE STATS"

        CONFIRM_RESET = (
            "🚨 <b>DANGER // DATA WIPE</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "Подтвердить обнуление статистики?\n"
            "⚠️ <b>ОПЕРАЦИЯ НЕОБРАТИМА.</b>"
        )
        RESET_DONE = "✅ <b>WIPED</b>"

        # Excel sheet/column titles
        XLS_SHEET_DAILY = "SIM DAILY"
        XLS_SHEET_SUMMARY = "SUMMARY"
        XLS_COLS = ["DATE", "IN", "OK", "REJ", "BLO", "NOS", "FAIL TOTAL"]
        XLS_TOTAL_LABEL = "TOTAL"
        XLS_PERIOD_LABEL = "PERIOD"
        XLS_FILENAME = "SIM_STATS_{month:02d}_{year}.xlsx"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Users  —  handlers/admin/users.py
    # ══════════════════════════════════════════════════════════════════════

    class Users:
        """Тексты управления агентами (admin/users.py)."""

        SEARCH_PROMPT = "🔍 <b>AGENT // SEARCH</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\nОтправьте Telegram ID пользователя:"
        ERR_INVALID_ID = "✖ <b>SYNTAX ERROR:</b> Числовой ID."
        ERR_SESSION = "✖ <b>SESSION ERROR</b>"
        ERR_BAD_DELTA = "✖ <b>INVALID DELTA:</b> <code>+15.50</code> / <code>-5.00</code>."

        # {tg_id}
        NOT_FOUND = "✖ <b>AGENT NOT FOUND</b>\nID: <code>{tg_id}</code>"
        # {tg_id} {pending_balance:.2f} {total_paid:.2f}
        BALANCE_PROMPT = (
            "💸 <b>CLEARING // CALIBRATION</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "▫ <b>AGENT:</b> <code>{tg_id}</code>\n"
            "▫ <b>PENDING:</b> <code>{pending_balance:.2f}</code> USDT\n"
            "▫ <b>PAID:</b> <code>{total_paid:.2f}</code> USDT\n\n"
            "ВВЕДИТЕ ДЕЛЬТУ (<code>+</code> / <code>-</code>):"
        )
        # {delta_sign} {delta_abs} {new_balance:.2f}
        BALANCE_UPDATED = (
            "✅ <b>CALIBRATED:</b> {delta_sign}{delta_abs} USDT.\nNEW BALANCE: <code>{new_balance:.2f}</code> USDT."
        )

        ALERT_NO_RIGHTS = "[ ACCESS DENIED ]"
        ALERT_NOT_FOUND = "[ NOT FOUND ]"
        ALERT_ERROR = "[ ERROR ]"
        ALERT_DM_SENT = "[ DM DELIVERED ]"
        ALERT_DM_FAILED = "[ DM FAILED ]"

        # {label} = "РАЗБАНЕН" / "ЗАБАНЕН"
        ALERT_BAN_TOGGLED = "[ AGENT {label} ]"
        BAN_LABEL_BANNED = "BANNED"
        BAN_LABEL_UNBANNED = "RESTORED"

        BTN_BACK_TO_DOSSIER = "◀ DOSSIER"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Archive  —  handlers/admin/archive.py
    # ══════════════════════════════════════════════════════════════════════

    class Archive:
        """Тексты поиска и архива (admin/archive.py)."""

        SEARCH_USAGE = "Format: /s 1234 or /s +79999999999"
        SEARCH_MIN = "Min 3 digits required."
        SEARCH_NAV = "▫ <b>SEARCH NAVIGATION</b>"
        SEARCH_EMPTY = "🌑 <b>NOT FOUND</b>"

        RESTRICT_DONE = "✅ Restricted"
        UNRESTRICT_DONE = "✅ Restored"

        ALERT_NO_RIGHTS = "[ ACCESS DENIED ]"
        ALERT_NOT_FOUND = "[ NOT FOUND ]"
        ERR_NO_RIGHTS = "✖ <b>ACCESS DENIED</b>"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Sys  —  handlers/admin/system.py
    # ══════════════════════════════════════════════════════════════════════

    class Sys:
        """Тексты системной диагностики (admin/system.py)."""

        SPINNER = "🛡 <b>SYSTEM INTEGRITY</b>\n\n📡 <code>RUNNING DIAGNOSTICS...</code>"
        DIVIDER = "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▰▰▰▰▰▰▰▰▰"

        STATUS_DB_OK = "ONLINE [OK]"
        STATUS_DB_FAIL = "⚠️ OFFLINE"
        STATUS_REDIS_OK = "ONLINE [OK]"
        STATUS_REDIS_FAIL = "⚠️ OFFLINE"

        # {db_line} {redis_line} {nodes} {uptime}
        REPORT = (
            "❖ <b>SYSTEM INTEGRITY // REPORT</b>\n"
            "{divider}\n"
            "┕ DATABASE: <code>{db_line}</code>\n"
            "┕ CACHE/FSM: <code>{redis_line}</code>\n"
            "┕ ACTIVE NODES: <code>{nodes}</code>\n"
            "┕ UPTIME: <code>{uptime}</code>"
        )

        BTN_REFRESH = "↻ RELOAD"
        BTN_CLEAR_FSM = "🧹 WIPE FSM CACHE"
        BTN_BACK = "◀ RETURN"

        # {deleted} — кол-во удалённых ключей
        FSM_CLEARED = "✅ <b>CLEARED:</b> <code>{deleted}</code> items."
        ALERT_NO_REDIS = "[ CACHE OFFLINE ]"
        ALERT_NO_RIGHTS = "[ ACCESS DENIED ]"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Analytics  —  handlers/admin/analytics.py
    # ══════════════════════════════════════════════════════════════════════

    class Analytics:
        """Тексты глобальной аналитики (admin/analytics.py)."""

        SPINNER = "👁️‍🗨️ <b>SYNDICATE EYE</b>\n\n📡 <code>COLLECTING DATA...</code>"
        DIVIDER = "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▰▰▰▰▰▰▰▰▰"

        # {total_turnover} {turnover_24h} {esim_accepted} {esim_rejected}
        # {pending_payouts_sum} {ts}
        REPORT = (
            "❖ <b>SYNDICATE EYE // GLOBAL REPORT</b>\n"
            "{divider}\n"
            "┕ TOTAL TURNOVER: <code>{total_turnover:,.2f} USDT</code>\n"
            "┕ TURNOVER 24H: <code>{turnover_24h:,.2f} USDT</code>\n"
            "┕ ASSETS (OK): <code>{esim_accepted:,} шт.</code>\n"
            "┕ ASSETS (REJ): <code>{esim_rejected:,} шт.</code>\n"
            "┕ PENDING DEBT: <code>{pending_payouts_sum:,.2f} USDT</code>\n"
            "{divider}\n"
            "<i>Sync: {ts}</i>"
        )
        BTN_REFRESH = "↻ RELOAD"
        ALERT_NO_RIGHTS = "[ ACCESS DENIED ]"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Mod  —  handlers/moderation_flow.py и moderation/
    # ══════════════════════════════════════════════════════════════════════

    class Mod:
        """Тексты модерационного потока."""

        QUEUE_EMPTY = "🌑 <b>NO PENDING DATA</b>\n<i>Очередь верификации пуста.</i>"
        TAKEN_TO_WORK = "✅ <b>LOCK ACQUIRED</b>\nКарточка взята в работу."
        FORWARD_DONE = "👁️‍🗨️ <b>DATA FORWARDED</b>"
        IN_REVIEW_ONLY = "✖ <b>STATUS ERROR</b>"

        # {count}
        BATCH_CONFIRM = "<b>BATCH // CONFIRM</b>\nОтправить <b>{count}</b> карточек?"
        # {ok} {failed}
        BATCH_DONE = "✅ <b>BATCH COMPLETE</b>\nSENT: {ok} | FAIL: {failed}."

        ALERT_NO_RIGHTS = "[ ACCESS DENIED ]"
        ALERT_NOT_FOUND = "[ NOT FOUND ]"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Academy —  handlers/admin/academy.py
    # ══════════════════════════════════════════════════════════════════════

    class Academy:
        """Тексты раздела академии (admin/academy.py)."""

        CODEX_HEADER = "🏯 <b>GDPX // ACADEMIC: CODEX</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"

        CODEX_TEXT = (
            "Агент.\n\n"
            "Ты не пришёл сюда случайно. Система уже зафиксировала твой потенциал.\n\n"
            "В Академии GDPX, знания конвертируются в капитал по высшим стандартам. "
            "Здесь нет легких путей - только безупречное исполнение и взаимное доверие.\n\n"

            "<b>ПРИНИМАЯ КОДЕКС АГЕНТА, ТЫ ОБЯЗУЕШЬСЯ:</b>\n\n"
            "▫ Поставлять исключительно чистый, проверенный материал\n"
            "▫ Соблюдать полную дисциплину и этику канала\n"
            "▫ Хранить внутренние знания и технологии Академии в строжайшей тайне\n"
            "▫ Работать на долгосрочный результат, а не на быстрый выхлоп\n"
            "▫ Поддерживать репутацию Академии на высшем уровне в любых сделках\n"
            "▫ Немедленно сообщать о любых рисках или нарушениях протокола\n\n"

            "<i>Готов ли ты войти в закрытый контур и стать частью элиты?</i>\n\n"
            "Нажми «Принимаю Кодекс», чтобы продолжить."
        )

        CODEX_ACCEPT_BUTTON = "✔️ ПРИНЯТЬ КОДЕКС"

        WELCOME_RECRUIT = (
            "🏯 <b>GDPX // ACADEMY: INNER CIRCLE</b>\n"
            "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱\n"
            "Приветствуем, Рекрут. Ваш цифровой след зафиксирован.\n\n"
            "▫ <b>Статус:</b> <code>ACTIVE</code>\n"
            "▫ <b>Допуск:</b> <code>LEVEL 1</code>\n\n"
            "<i>Система готова к эксплуатации.</i>"
        )

        MENU_OPENED = "Система загружена. Навигация по меню системы ↴"

    # ══════════════════════════════════════════════════════════════════════
    # АРХИВ СЕЛЛЕРА
    # ══════════════════════════════════════════════════════════════════════

    BTN_ARCHIVE = "📦 АРХИВ"

    class SellerArchive:
        """Тексты раздела архива селлера."""

        HEADER = "📦 <b>ARCHIVE // STORAGE</b>\n▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
        EMPTY = "🌑 <b>EMPTY</b>\nАрхивные данные отсутствуют."
        INFO = "<i>В архиве хранятся симки, загруженные в предыдущие циклы.</i>"
