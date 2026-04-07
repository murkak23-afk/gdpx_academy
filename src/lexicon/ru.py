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
    from src.lexicon.ru import Lex
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
        "🛑 <b>[СИСТЕМА] // СБОЙ СВЯЗИ</b>\n\n"
        "Центральный сервер базы данных недоступен.\n"
        "Ведутся работы по восстановлению контура. Ожидайте — /start"
    )
    # Backward compatibility alias for older imports.
    EERR_DB_UNAVAILABLE = ERR_DB_UNAVAILABLE

    ERR_NO_RIGHTS = "В доступе отказано. Требуется уровень: ARCHITECT."
    ERR_NO_RIGHTS_ALERT = "[ ROOT ACCESS DENIED ]"

    ERR_SESSION_EXPIRED = "Токен сессии истек. Инициируйте выплату заново."
    ERR_AMOUNT_CORRUPT  = "Сбой калибрации: неверный формат суммы."
    ERR_WITHDRAW_FAILED = "CryptoBot отклонил запрос. Повторите цикл позже."

    # ══════════════════════════════════════════════════════════════════════
    # РЕГИСТРАЦИЯ / ОНБОРДИНГ
    # ══════════════════════════════════════════════════════════════════════

    ASK_LANGUAGE = (
        "❖ <b>GDPX // ACADEMY: INITIALIZATION</b>\n\n"
        "Установите языковой пакет интерфейса:"
    )

    # {requirements} подставляется в шаблон, чтобы правила можно было изменить отдельно
    ASK_PSEUDONYM = (
        "🏷 <b>ИДЕНТИФИКАТОР (ПСЕВДОНИМ)</b>\n\n"
        "Этот позывной будет отображаться в глобальном реестре (Leaderboard).\n\n"
        "▫ 2–32 символа\n"
        "▫ буквы, цифры, <code>_</code> и <code>-</code>\n"
        "▫ <b>не подлежит изменению</b> после инициализации\n\n"
        "Введите позывной:"
    )

    ASK_LANGUAGE_ONLY_BUTTON = "Пожалуйста, выбери язык кнопкой ниже."

    WARN_PSEUDONYM_INVALID = (
        "⚠️ <b>Отказ. Нарушен синтаксис.</b>\n"
        "Допускаются только буквы, цифры, <code>_</code> и <code>-</code> (от 2 до 32 символов).\n"
        "Введите корректный ID:"
    )
    WARN_PSEUDONYM_TAKEN = "⚠️ <b>Отказ.</b> Идентификатор уже используется кем то другим. Введите уникальный ID:"

    # ══════════════════════════════════════════════════════════════════════
    # ВЫВОД СРЕДСТВ (/withdraw)
    # ══════════════════════════════════════════════════════════════════════

    ERR_WITHDRAW_USAGE   = "Синтаксическая ошибка. Формат ввода: <code>/withdraw 10.5</code>"
    ERR_WITHDRAW_ZERO    = "Ошибка ликвидности. Сумма вывода должна быть больше нуля."

    # {amount} — строковое представление Decimal
    ASK_WITHDRAW_CONFIRM = "Подтвердить транзакцию: <b>{amount} USDT</b>?"

    OK_WITHDRAW_DONE  = "Транзакция в обработке..."
    # {check_url} — ссылка CryptoBot
    OK_WITHDRAW_CHECK = "✅ <b>КЛИРИНГ УСПЕШЕН</b>\nСгенерирован чек для обналичивания:\n{check_url}"

    OK_CANCEL = "Процесс прерван."

    # ══════════════════════════════════════════════════════════════════════
    # ЛЕАДЕРБОРД — продавец
    # ══════════════════════════════════════════════════════════════════════

    # {week} — номер недели
    LEAD_HEADER           = "❖ <b>GDPX // LEADERBOARD #{week}</b>"
    LEAD_ACTIVE_BONUS_HDR = "⚠️ <b>ПРИОРИТЕТ ЦИКЛА [БОНУС]:</b>"
    LEAD_TOP_DEFAULT      = "<code>[АВАНГАРД СЕТИ // ТОП-5 ОПЕРАТОРОВ]</code>"
    LEAD_EMPTY            = "🌑 <b>ЛОГИ ПУСТЫ</b>\n<i>Трафик за текущий цикл не зафиксирован.</i>"

    # {rank} {score}
    LEAD_USER_RANK  = "🎯 <b>ТВОЯ ПОЗИЦИЯ: #{rank}</b> (Активов: {score})"
    LEAD_USER_NORANK = "🎯 <b>[ТВОЙ SCORE]:</b> <code>IDLE</code> (0 активов)\n<i>Система ожидает твой первый трафик.</i>"

    # ══════════════════════════════════════════════════════════════════════
    # ЛЕАДЕРБОРД — админ (/alead)
    # ══════════════════════════════════════════════════════════════════════

    ALEAD_HEADER     = "❖ <b>ARCHITECT // НАСТРОЙКА L-BOARD</b>"
    ALEAD_STATUS_ON  = "🟢 АКТИВЕН"
    ALEAD_STATUS_OFF = "🔴 ОТКЛЮЧЕН"
    ALEAD_NO_PRIZE_TEXT = "<code>[ ПУСТО ]</code>"
    ALEAD_HINT       = "<i>Терминал управления стимулами:</i>"

    # {state} — "ВКЛЮЧЁН" или "ВЫКЛЮЧЕН"
    ALEAD_TOGGLED = "Приз: <b>{state}</b>"

    ALEAD_ASK_PRIZE_TEXT = (
        "✏️ <b>ИНИЦИАЛИЗАЦИЯ БОНУСА</b>\n\n"
        "Введите условия вознаграждения (лимит 512 символов).\n"
        "Данные будут транслироваться всем операторам сети при активном протоколе.\n\n"
        "Для прерывания операции нажмите Отмену."
    )
    ALEAD_PRIZE_SAVED = "✅ Директива успешно сохранена в ядре.\n\n"

    # ══════════════════════════════════════════════════════════════════════
    # КНОПКИ (дублируются в keyboards.inline, чтобы хендлеры могли взять из lexicon)
    # ══════════════════════════════════════════════════════════════════════

    BTN_CONFIRM      = "✔️ ACCEPT"
    BTN_CANCEL       = "✖️ ABORT"
    BTN_BACK         = "◂ RETURN"
    BTN_REFRESH      = "↻ RELOAD LOGS"
    BTN_PRIZE_TOGGLE_ON  = "🟢 АКТИВИРОВАТЬ БОНУС"
    BTN_PRIZE_TOGGLE_OFF = "🔴 ЗАМОРОЗИТЬ БОНУС"
    BTN_PRIZE_EDIT   = "⚙️ ИЗМЕНИТЬ ДИРЕКТИВУ"
    BTN_WDR_CONFIRM  = "✔️ EXECUTE (ВЫВОД)"

    BTN_TERMINATE_SESSION = "⊗ ЗАВЕРШИТЬ СЕССИЮ"
    BTN_TERMINATE_CONFIRM = "◾ ПОДТВЕРДИТЬ ОЧИСТКУ"

    # ══════════════════════════════════════════════════════════════════════
    # PANIC BUTTON / SESSION CLEANUP
    # ══════════════════════════════════════════════════════════════════════

    INFO_SESSION_TERMINATE_CONFIRM = (
        "❖ <b>GDPX // PROTOCOL: CLEANUP</b>\n\n"
        "Внимание. Инициирован полный сброс сессии.\n"
        "Текущий контекст и недавние логи терминала будут безвозвратно стерты.\n\n"
        "⚠️ <b>ОПЕРАЦИЯ НЕОБРАТИМА.</b> Исполнить?"
    )

    INFO_SESSION_TERMINATED = (
        "🌑 <code>[ СЕССИЯ АННУЛИРОВАНА // ЛОГИ СТЕРТЫ ]</code>"
    )

    # ══════════════════════════════════════════════════════════════════════
    # ПРАВА / МОДЕРАЦИЯ (общие)
    # ══════════════════════════════════════════════════════════════════════

    WARN_ACCESS_DENIED_ALERT = "[ ROOT ACCESS DENIED ]"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Support  —  seller/info.py → on_seller_menu_support
    # ══════════════════════════════════════════════════════════════════════

    class Support:
        """SUPPORT CENTER — экран поддержки продавца."""

        HEADER  = "❖ <b>GDPX // SUPPORT CENTER</b>"
        DIVIDER = "━━━━━━━━━━━━━━━━━━━━"
        STATUS  = "[🟢 <b>ONLINE</b>] ── <i>Отклик: 15 MIN.</i>"

        # Плейсхолдеры: {divider} {founder} {helper_1} {helper_2} {architect} {status}
        BODY = (
            "{header}\n"
            "{divider}\n"
            "🌑 <b>ОСНОВАТЕЛЬ</b> ── {founder}\n"
            "  └─<i>Ресурсная база / Глобальный выкуп</i>\n\n"
            "🛡 <b>САППОРТЫ</b> ── {helper_1} | {helper_2}\n"
            "  └─<i>Наставление / Прием материала</i>\n\n"
            "⚙️ <b>АРХИТЕКТОР</b> ── {architect}\n"
            "  └─<i>Технические вопросы / Бот</i>\n"
            "{divider}\n"
            "{status}\n"
        )

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Sub  —  seller/submission.py
    # ══════════════════════════════════════════════════════════════════════

    class Sub:
        """Тексты FSM-потока загрузки материалов (submission)."""

        ERR_RESTRICTED = (
            "У ТЕБЯ ВРЕМЕННОЕ ОГРАНИЧЕНИЕ. ПОДТВЕРДИ, ЧТО ТЫ ЧЕЛОВЕК."
        )
        # {until} — datetime строкой
        ERR_TIMEOUT = (
            "ВРЕМЕННЫЙ ТАЙМАУТ ЗА ДУБЛИКАТЫ ДО {until}."
        )
        ERR_NO_CATEGORY = (
            "СНАЧАЛА ВЫБЕРИ КАТЕГОРИЮ (ПОДТИП ОПЕРАТОРА)."
        )
        ERR_NO_QUOTA = (
            "НА СЕГОДНЯ В ЭТОЙ КАТЕГОРИИ НЕ НАЗНАЧЕН ЛИМИТ ВЫГРУЗОК. "
            "АДМИНИСТРАТОР ЗАДАЁТ ЛИМИТЫ ЧЕРЕЗ /ADM_CAT."
        )
        # {limit} — int, дневной лимит
        ERR_QUOTA_EXCEEDED = (
            "ДОСТИГНУТ ДНЕВНОЙ ЛИМИТ ПО ЗАПРОСУ В ЭТОЙ КАТЕГОРИИ: {limit}. "
            "НОВЫЕ СИМКИ — ЗАВТРА (UTC) ИЛИ ПОСЛЕ СМЕНЫ ЗАПРОСА."
        )

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Pay  —  handlers/admin/payouts.py
    # ══════════════════════════════════════════════════════════════════════

    class Pay:
        """Тексты раздела выплат (admin/payouts.py)."""

        LEDGER_HEADER  = "💸 ВЕДОМОСТЬ ВЫПЛАТ"
        LEDGER_EMPTY   = "НЕТ ПОЛЬЗОВАТЕЛЕЙ С ОЖИДАЮЩИМИ ВЫПЛАТАМИ."

        HISTORY_HEADER = "📜 ИСТОРИЯ ВЫПЛАТ"
        HISTORY_EMPTY  = "ПОКА ПУСТО."

        TRASH_HEADER   = "🗑 КОРЗИНА ВЫПЛАТ"
        TRASH_EMPTY    = "ПОКА ПУСТО."

        PENDING_HEADER = "⚙️ УПРАВЛЕНИЕ ВЫПЛАТАМИ"
        PENDING_EMPTY  = "🔴 ВЫПЛАТ НЕТ."

        # Кнопки навигации ведомости
        BTN_TOPUP          = "💳 ДОБАВИТЬ USDT"
        BTN_HISTORY        = "📜 ИСТОРИЯ ВЫПЛАТ"
        BTN_TRASH          = "🗑 КОРЗИНА"
        BTN_PENDING_MANAGE = "⚙️ УПРАВЛЕНИЕ ВЫПЛАТОЙ"
        BTN_TO_LEDGER      = "💸 К ВЕДОМОСТИ"

        ERR_NO_EXPORT_DATA = "НЕТ ДАННЫХ ДЛЯ ЭКСПОРТА."
        ERR_NO_RIGHTS      = "НЕДОСТАТОЧНО ПРАВ."

        # Alert-сообщения (show_alert=True)
        ALERT_NO_RIGHTS         = "НЕДОСТАТОЧНО ПРАВ"
        ALERT_BAD_DATA          = "НЕКОРРЕКТНЫЕ ДАННЫЕ"
        ALERT_USER_NOT_FOUND    = "ПОЛЬЗОВАТЕЛЬ НЕ НАЙДЕН"
        ALERT_NO_PENDING        = "НЕТ ОЖИДАЮЩИХ ВЫПЛАТ ДЛЯ ЭТОГО ПОЛЬЗОВАТЕЛЯ"
        ALERT_INVOICE_BAD_ID    = "НЕКОРРЕКТНЫЙ INVOICE ID"
        ALERT_INVOICE_NOT_PAID  = "INVOICE ЕЩЁ НЕ ОПЛАЧЕН"
        ALERT_SESSION_LOST      = "ДАННЫЕ СЕССИИ ПОТЕРЯНЫ"
        ALERT_INVOICE_FAILED    = "НЕ УДАЛОСЬ СОЗДАТЬ INVOICE"
        # {amount} {asset}
        ALERT_TOPUP_OK          = "✅ APP ПОПОЛНЕН НА {amount} {asset}"

        PAID_CANCEL_ALERT       = "ОПЛАТА ОТМЕНЕНА"

        # {username} {total_accepted} {rejected} {total_amount}
        CONFIRM_STEP1 = (
            "❖ <b>GDPX // ЭМИССИЯЮ [01/02]</b>\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
            "► <b>[АУДИТ УЗЛА]:</b> <code>{username}</code>\n"
            "► <b>[ВРЕМЕННОЙ ЦИКЛ]:</b> СЕССИЯ АКТИВНА (UTC)\n\n"
            "❂ <b>[СВОДКА АКТИВОВ]:</b>\n"
            "  ├ 🟢 <b>[VALID]:</b>  <code>{total_accepted} шт.</code>\n"
            "  └ 🔴 <b>[REJECT]:</b> <code>{rejected} шт.</code>\n\n"
            "❂ <b>[РАСЧЕТНАЯ ВЕДОМОСТЬ]:</b>\n"
            "  └ <b>К ВЫПЛАТЕ:</b> <code>{total_amount} USDT</code>\n\n"
            "<i>[!] КОЭФФИЦИЕНТЫ ПРИМЕНЕНЫ СОГЛАСНО УРОВНЮ ДОПУСКА.</i>\n\n"
            "<b>► ИНИЦИИРОВАТЬ ТРАНЗАКЦИЮ?</b>"
        )
        # {total_amount} {username} {balance_line} {warning_line}
        CONFIRM_STEP2 = (
            "❖ <b>GDPX // ЭМИССИЯ [02/02]</b>\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
            "<b>[ОЖИДАНИЕ КОРНЕВОЙ ПОДПИСИ]</b>\n\n"
            "❖ <b>[ДЕТАЛИ ТРАНЗАКЦИИ]:</b>\n"
            "  ├ <b>ОБЪЕМ:</b> <code>{total_amount} USDT</code>\n"
            "  └ <b>ЦЕЛЬ:</b>  <code>{username}</code>\n\n"
            "❖ <b>[СТАТУС]:</b>\n"
            "{balance_line}\n"
            "{warning_line}\n\n"
            "⚠️ <i>[CRITICAL] ИСПОЛНЕНИЕ ДЕЙСТВИЯ НЕОБРАТИМО. ВЫПЛАЧЕННЫЕ АКТИВЫ БУДУТ АРХИВИРОВАНЫ.</i>\n\n"
            "<b>► ФИКСИРОВАТЬ ХЭШ?</b>"
        )
        CONFIRM_STEP2_BALANCE_OK   = "  └ 🟢 <b>[ДОПУСК ПОЛУЧЕН]:</b> РЕЗЕРВ ИНФРАСТРУКТУРЫ ПОДТВЕРЖДЕН."
        CONFIRM_STEP2_BALANCE_LOW  = "  └ 🔴 <b>[ОТКАЗ]:</b> ИСТОЩЕНИЕ КРИПТО-ПУЛА. ТРЕБУЕТСЯ ВЛИВАНИЕ ЛИКВИДНОСТИ."
        
        CONFIRM_STEP2_BALANCE_LINE = "  ├ <b>ЛИКВИДНОСТЬ:</b> <code>{balance} USDT</code>"
        CONFIRM_STEP2_BALANCE_ERR  = "  └ 🔴 <b>[СБОЙ СВЯЗИ]:</b> ОТКАЗ API ШЛЮЗА ({error})"

        TOPUP_ASK = (
            "💸 <b>ПОПОЛНЕНИЕ APP БАЛАНСА</b>\n\n"
            "ВВЕДИТЕ ОБЪЕМ ТРАНША В USDT.\n"
            "<i>Синтаксис: только числовое значение.</i>"
        )
        TOPUP_RESERVE_HDR = "❖ <b>GDPX // CRYPTOPAY</b>"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Mailing  —  handlers/admin/mailing.py
    # ══════════════════════════════════════════════════════════════════════

    class Mailing:
        """Тексты модуля рассылки (admin/mailing.py)."""

        ASK_INPUT = (
            "📡 <b>РАССЫЛКА</b>\n\n"
            "ОТПРАВЬ ТЕКСТ СООБЩЕНИЯ ОДНИМ СООБЩЕНИЕМ.\n"
            "МОЖНО ПРИКРЕПИТЬ ФОТО — ТОДА ОТПРАВЬ ФОТО С ПОДПИСЬЮ.\n\n"
            "{hint}"
        )
        ERR_EMPTY = "СООБЩЕНИЕ ПУСТОЕ. ОТПРАВЬ ТЕКСТ ИЛИ ФОТО С ПОДПИСЬЮ."

        # {has_photo} "да"/"нет", {preview_body}
        PREVIEW = (
            "📋 <b>ПРЕВЬЮ РАССЫЛКИ</b>\n\n"
            "<b>ФОТО:</b> {has_photo}\n"
            "<b>ТЕКСТ:</b>\n"
            "<blockquote>{preview_body}</blockquote>\n\n"
            "ЗАПУСТИТЬ РАССЫЛКУ?"
        )
        PREVIEW_PHOTO_YES = "да"
        PREVIEW_PHOTO_NO  = "нет"

        # {ok} {blocked} {failed}
        REPORT = (
            "📡 <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n\n"
            "✔️ ДОСТАВЛЕНО: <b>{ok}</b>\n"
            "🚫 ЗАБЛОКИРОВАЛИ БОТА: <b>{blocked}</b>\n"
            "⚠️ ОШИБОК: <b>{failed}</b>"
        )
        ERR_NO_RIGHTS   = "НЕДОСТАТОЧНО ПРАВ."
        ALERT_NO_RIGHTS = "НЕДОСТАТОЧНО ПРАВ"

        BTN_LAUNCH = "◉ ЗАПУСТИТЬ"
        BTN_CANCEL = "✖ ОТМЕНА"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Stats  —  handlers/admin/stats.py
    # ══════════════════════════════════════════════════════════════════════

    class Stats:
        """Тексты раздела статистики (admin/stats.py)."""

        # {month:02d} {year}
        HEADER       = "📊 <b>СТАТИСТИКА SIM ЗА {month:02d}.{year} (UTC)</b>"
        TABLE_HEADER = "<code>ДЕНЬ | ВХОД | ✔️ | ❌ | 🚫 | ⛔</code>"
        TOTAL_LABEL  = "<b>ИТОГО ЗА МЕСЯЦ</b>"

        # {total_incoming} {total_accepted} {total_failed} {rejected} {blocked} {not_scan}
        TOTAL_ROW = (
            "💠 ВХОДЯЩИЕ SIM: <b>{total_incoming}</b>\n"
            "✔️ ПРИНЯТО: <b>{total_accepted}</b>\n"
            "❌ БРАК ВСЕГО: <b>{total_failed}</b> "
            "(REJECTED={rejected}, BLOCKED={blocked}, NOT A SCAN={not_scan})"
        )
        BTN_EXPORT  = "🌸 ВЫГРУЗИТЬ EXCEL"
        BTN_RESET   = "🗑 ОБНУЛИТЬ СТАТИСТИКУ"

        CONFIRM_RESET = (
            "⚠️ ПОДТВЕРДИТЬ ОБНУЛЕНИЕ СТАТИСТИКИ?\n"
            "ИСТОРИЮ НЕЛЬЗЯ ВОССТАНОВИТЬ."
        )
        RESET_DONE = "✔️ СТАТИСТИКА ОБНУЛЕНА."

        # Excel sheet/column titles
        XLS_SHEET_DAILY   = "SIM DAILY"
        XLS_SHEET_SUMMARY = "SUMMARY"
        XLS_COLS          = ["ДАТА", "ВХОДЯЩИЕ", "ПРИНЯТО", "REJECTED", "BLOCKED", "NOT A SCAN", "БРАК ВСЕГО"]
        XLS_TOTAL_LABEL   = "ИТОГО"
        XLS_PERIOD_LABEL  = "ПЕРИОД"
        XLS_FILENAME      = "SIM_STATS_{month:02d}_{year}.xlsx"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Users  —  handlers/admin/users.py
    # ══════════════════════════════════════════════════════════════════════

    class Users:
        """Тексты управления агентами (admin/users.py)."""

        SEARCH_PROMPT = (
            "🔍 <b>ПОИСК АГЕНТА</b>\n\n"
            "ОТПРАВЬ TELEGRAM ID ПОЛЬЗОВАТЕЛЯ (ЧИСЛОВОЙ):"
        )
        ERR_INVALID_ID = "TELEGRAM ID — ЭТО ЧИСЛО. ПОПРОБУЙ ЕЩЁ РАЗ:"
        ERR_SESSION    = "ОШИБКА СЕССИИ. НАЧНИ ПОИСК ЗАНОВО."
        ERR_BAD_DELTA  = (
            "НЕВЕРНЫЙ ФОРМАТ. ПРИМЕРЫ: <code>+15.50</code>, <code>-5.00</code>."
        )

        # {tg_id}
        NOT_FOUND = (
            "СЕЛЛЕР С TG ID <code>{tg_id}</code> НЕ НАЙДЕН В БАЗЕ.\n"
            "ПРОВЕРЬ ID И ОТПРАВЬ СНОВА."
        )
        # {tg_id} {pending_balance:.2f} {total_paid:.2f}
        BALANCE_PROMPT = (
            "💸 <b>ИЗМЕНИТЬ СУММУ К ВЫПЛАТЕ</b>\n\n"
            "СЕЛЛЕР: <code>{tg_id}</code>\n"
            "ТЕКУЩАЯ СУММА К ВЫПЛАТЕ: <code>{pending_balance:.2f}</code> USDT\n"
            "ВСЕГО ВЫПЛАЧЕНО: <code>{total_paid:.2f}</code> USDT\n\n"
            "ВВЕДИ СУММУ: <code>+15.50</code> (добавить) или <code>-5.00</code> (вычесть):"
        )
        # {delta_sign} {delta_abs} {new_balance:.2f}
        BALANCE_UPDATED = (
            "💸 БАЛАНС СКОРРЕКТИРОВАН: {delta_sign}{delta_abs} USDT.\n"
            "НОВОЕ ЗНАЧЕНИЕ: <code>{new_balance:.2f}</code> USDT."
        )

        ALERT_NO_RIGHTS    = "НЕДОСТАТОЧНО ПРАВ"
        ALERT_NOT_FOUND    = "СЕЛЛЕР НЕ НАЙДЕН"
        ALERT_ERROR        = "ОШИБКА"
        ALERT_DM_SENT      = "✔️ СООБЩЕНИЕ ДОСТАВЛЕНО."
        ALERT_DM_FAILED    = "⚠️ НЕ УДАЛОСЬ ОТПРАВИТЬ."

        # {label} = "РАЗБАНЕН" / "ЗАБАНЕН"
        ALERT_BAN_TOGGLED  = "✔️ СЕЛЛЕР {label}"
        BAN_LABEL_BANNED   = "ЗАБАНЕН"
        BAN_LABEL_UNBANNED = "РАЗБАНЕН"

        BTN_BACK_TO_DOSSIER = "◀ К ДОСЬЕ"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Archive  —  handlers/admin/archive.py
    # ══════════════════════════════════════════════════════════════════════

    class Archive:
        """Тексты поиска и архива (admin/archive.py)."""

        SEARCH_USAGE    = "Формат: /s 1234 или /s +79999999999"
        SEARCH_MIN      = "Укажи минимум 3 последние цифры или полный номер."
        SEARCH_NAV      = "Навигация поиска:"
        SEARCH_EMPTY    = "Ничего не найдено по этому запросу."

        RESTRICT_DONE   = "Ограничение включено"
        UNRESTRICT_DONE = "Ограничение снято"

        ALERT_NO_RIGHTS   = "НЕДОСТАТОЧНО ПРАВ"
        ALERT_NOT_FOUND   = "ПОЛЬЗОВАТЕЛЬ НЕ НАЙДЕН"
        ERR_NO_RIGHTS     = "Недостаточно прав."

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Sys  —  handlers/admin/system.py
    # ══════════════════════════════════════════════════════════════════════

    class Sys:
        """Тексты системной диагностики (admin/system.py)."""

        SPINNER  = "🛡 <b>SYSTEM INTEGRITY</b>\n\n⏳ ДИАГНОСТИКА…"
        DIVIDER  = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"

        STATUS_DB_OK      = "ONLINE [OK]"
        STATUS_DB_FAIL    = "⚠️ OFFLINE"
        STATUS_REDIS_OK   = "ONLINE [OK]"
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

        BTN_REFRESH   = "↻ ОБНОВИТЬ"
        BTN_CLEAR_FSM = "🧹 УДАЛИТЬ УСТАРЕВШИЕ FSM"
        BTN_BACK      = "◀ К СТАТУСУ"

        # {deleted} — кол-во удалённых ключей
        FSM_CLEARED    = "✔️ УДАЛЕНО УСТАРЕВШИХ FSM-КЛЮЧЕЙ: <b>{deleted}</b>"
        ALERT_NO_REDIS = "⚠️ REDIS НЕДОСТУПЕН — ОПЕРАЦИЯ НЕВОЗМОЖНА."
        ALERT_NO_RIGHTS = "НЕДОСТАТОЧНО ПРАВ"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Analytics  —  handlers/admin/analytics.py
    # ══════════════════════════════════════════════════════════════════════

    class Analytics:
        """Тексты глобальной аналитики (admin/analytics.py)."""

        SPINNER = "👁️‍🗨️ <b>SYNDICATE EYE</b>\n\n⏳ ФОРМИРОВАНИЕ ОТЧЁТА…"
        DIVIDER = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"

        # {total_turnover} {turnover_24h} {esim_accepted} {esim_rejected}
        # {pending_payouts_sum} {ts}
        REPORT = (
            "❖ <b>SYNDICATE EYE // GLOBAL REPORT</b>\n"
            "{divider}\n"
            "┕ ОБЩИЙ ОБОРОТ: <code>{total_turnover:,.2f} USDT</code>\n"
            "┕ ОБОРОТ 24Ч: <code>{turnover_24h:,.2f} USDT</code>\n"
            "┕ ВЫДАНО eSIM: <code>{esim_accepted:,} шт.</code> (успешных)\n"
            "┕ ОТКЛОНЕНО eSIM: <code>{esim_rejected:,} шт.</code>\n"
            "┕ ПРЕДСТОЯЩАЯ ВЫПЛАТА: <code>{pending_payouts_sum:,.2f} USDT</code>\n"
            "{divider}\n"
            "⌄ СВОДКА СФОРМИРОВАНА: <i>{ts}</i>"
        )
        BTN_REFRESH   = "↻ ОБНОВИТЬ"
        ALERT_NO_RIGHTS = "НЕДОСТАТОЧНО ПРАВ"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Mod  —  handlers/moderation_flow.py и moderation/
    # ══════════════════════════════════════════════════════════════════════

    class Mod:
        """Тексты модерационного потока."""

        QUEUE_EMPTY    = "🌑 <b>ОЧЕРЕДЬ ПУСТА</b>\n<i>НОВЫХ МАТЕРИАЛОВ НЕТ.</i>"
        TAKEN_TO_WORK  = "✔️ КАРТОЧКА ВЗЯТА В РАБОТУ."
        FORWARD_DONE   = "👁️‍🗨️ МАТЕРИАЛЫ ПЕРЕДАНЫ."
        IN_REVIEW_ONLY = "КАРТОЧКА ДОЛЖНА НАХОДИТЬСЯ В СТАТУСЕ IN_REVIEW ДЛЯ ЭТОГО ДЕЙСТВИЯ."

        # {count}
        BATCH_CONFIRM  = "ПОДТВЕРДИТЬ ОТПРАВКУ <b>{count}</b> КАРТОЧЕК?"
        # {ok} {failed}
        BATCH_DONE     = "✔️ ПЕРЕСЛАНО: {ok}. ОШИБОК: {failed}."

        ALERT_NO_RIGHTS = "НЕДОСТАТОЧНО ПРАВ"
        ALERT_NOT_FOUND = "КАРТОЧКА НЕ НАЙДЕНА"

    # ══════════════════════════════════════════════════════════════════════
    # NAMESPACE: Lex.Academy —  handlers/admin/academy.py
    # ══════════════════════════════════════════════════════════════════════


    class Academy:
        """Тексты раздела академии (admin/academy.py)."""

        CODEX_HEADER = (
            "❖ GDPX // ACADEMY - Terminal v2.3\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
            "❂ КОДЕКС АГЕНТА\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"
        )

        CODEX_TEXT = (
            "Агент.\n\n"
            "Ты не пришёл сюда случайно.\n"
            "Ты здесь, потому что система уже показала тебе свою истинную цену.\n\n"
            "В Академии GDPX мы не обещаем лёгких денег.\n"
            "Мы учим видеть качество там, где другие видят только риск.\n"
            "Мы учим ждать, когда другие спешат.\n"
            "Мы учим молчать, когда другие болтают.\n\n"
            "Принимая Кодекс, ты соглашаешься:\n"
            "• Поставлять только чистый актив\n"
            "• Никогда не нарушать дисциплину\n"
            "• Хранить знания Академии до конца\n"
            "• Работать только через систему\n\n"
            "Здесь рождаются те, кто перестаёт проигрывать.\n\n"
            "Готов ли ты принять Кодекс и стать одним из нас?"
        )

        CODEX_ACCEPT_BUTTON = "✅ Принимаю Кодекс и вступаю в Академию"

        PIN_PROMPT = (
            "❂ УСТАНОВКА ЛИЧНОГО КОДА ДОСТУПА\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
            "Введите ваш личный код доступа агента\n"
            "╰┈➤ (4–6 цифр)"
        )

        PIN_CONFIRM_PROMPT = "╰┈➤ Подтвердите код доступа агента:"

        PIN_MISMATCH = "〇 Коды доступа не совпадают."

        PIN_SUCCESS = "✅ Код доступа успешно активирован."

        WELCOME_RECRUIT = (
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
            "❂ ДОБРО ПОЖАЛОВАТЬ В ЗАКРЫТЫЙ КОНТУР\n"
            "Академии GDPX, Рекрут.\n\n"
            "Ваш статус активирован.\n"
            "Доступ к системе предоставлен.\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"
)

        WELCOME_RECRUIT = (
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
            "ДОБРО ПОЖАЛОВАТЬ В ЗАКРЫТЫЙ КОНТУР\n"
            "Академии GDPX, Рекрут.\n\n"
            "Ваш статус активирован.\n"
            "Доступ к системе предоставлен.\n"
            "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"
        )

        MENU_OPENED = "Система загружена. Навигация по меню системы ↴"