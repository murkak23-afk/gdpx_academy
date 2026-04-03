# GDPX | WORK BOT

**A production-ready Telegram bot for digital goods (eSIM) collection and moderation, built on aiogram 3.x, async SQLAlchemy, PostgreSQL, and Redis.**

---

## Содержание

- [О проекте](#о-проекте)
- [Возможности](#возможности)
- [Структура проекта](#структура-проекта)
- [Быстрый старт (Docker)](#быстрый-старт-docker)
- [Локальная разработка](#локальная-разработка)
- [Переменные окружения](#переменные-окружения)
- [Скрипты обслуживания](#скрипты-обслуживания)
- [Тесты](#тесты)
- [Стек технологий](#стек-технологий)

---

## О проекте

GDPX Work Bot — система приёма и модерации eSIM от продавцов (sellers) с панелью администратора, FSM-флоу загрузки, батч-обработкой, экспортом CSV, выплатами через Crypto Pay и встроенным health-check API.

---

## Возможности

- **Модульная архитектура.** Каждый домен изолирован в своём пакете хендлеров (`handlers/seller/`, `handlers/admin/`, `handlers/moderation/`). Нет монолитных файлов.
- **FSM-флоу загрузки.** Продавец проходит шаги «категория → фото/документ → номер телефона» через `aiogram.fsm`. Батч-режим: загрузка потоком с единым статус-сообщением.
- **Защита от дубликатов.** SHA-256 hash по `file_unique_id` на уровне БД; автоматический таймаут нарушителю.
- **Дневные квоты на категорию.** Гибкое ограничение выгрузок через `SellerQuotaService`.
- **Панель администратора.** Рассылка, архив, статистика, управление выплатами, конструктор категорий — всё через Telegram inline-кнопки.
- **Async PostgreSQL + Alembic.** `asyncpg` для runtime, `psycopg` для миграций. Unit of Work в слое middleware.
- **Redis FSM Storage.** При наличии `REDIS_URL` FSM-состояния выживают при рестарте.
- **Health-check API.** FastAPI + uvicorn в одном процессе с ботом: `GET /health` (liveness) и `GET /health/ready` (readiness, опционально проверяет Crypto Pay).
- **TTL-троттлинг.** `cachetools.TTLCache` без Redis — защита от флуда на уровне middleware.

---

## Структура проекта

```
src/
├── core/           # config (pydantic-settings), dispatcher, bot, error handlers
├── database/       # SQLAlchemy models, repository layer, Alembic env
├── handlers/
│   ├── admin/      # панель администратора
│   │   ├── archive.py      ← работа с архивом заявок
│   │   ├── mailing.py      ← рассылка
│   │   ├── menu.py         ← главное меню админа
│   │   ├── payouts.py      ← управление выплатами
│   │   └── stats.py        ← статистика
│   ├── seller/             # продавец (eSIM upload)
│   │   ├── _shared.py      ← константы, batch-утилиты, FSM-хелперы
│   │   ├── info.py         ← FAQ, мануалы, support
│   │   ├── materials.py    ← просмотр и редактирование материалов
│   │   ├── submission.py   ← FSM-флоу загрузки (category→photo→batch→CSV)
│   │   └── profile.py      ← профиль, статистика, выплаты, капча
│   └── moderation/         # флоу модерации заявок
├── keyboards/      # inline / reply клавиатуры, CallbackData
├── middlewares/    # db_session (Unit of Work), throttling, logging
├── services/       # бизнес-логика (AdminService, SubmissionService, …)
├── states/         # aiogram FSM StatesGroup
└── utils/          # форматтеры, медиа-хелперы, clean-screen
alembic/versions/   # миграции БД (25 версий)
scripts/            # CLI-утилиты обслуживания
tests/              # pytest unit-тесты
```

---

## Быстрый старт (Docker)

> Требования: Docker ≥ 24, Docker Compose v2.

### 1. Склонировать и настроить окружение

```bash
git clone https://github.com/your-org/gdpx-work-bot.git
cd gdpx-work-bot

cp .env.example .env
```

Открой `.env` и заполни обязательные поля:

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен из `@BotFather` |
| `POSTGRES_PASSWORD` | Сложный пароль БД |
| `MODERATION_CHAT_ID` | `chat_id` группы модерации (отрицательное число) |

### 2. Собрать и поднять

```bash
docker compose up -d --build
```

Docker Compose поднимет три сервиса: `postgres`, `redis`, `bot`.  
Бот автоматически применяет миграции (`alembic upgrade head`) перед запуском.

### 3. Назначить первого администратора

```bash
docker compose exec bot python scripts/make_admin.py --telegram-id YOUR_TELEGRAM_ID --role admin
```

### 4. Полезные команды

```bash
# Логи бота в реальном времени
docker compose logs -f bot

# Health-check
curl http://localhost:8000/health
curl http://localhost:8000/health/ready

# Остановить всё
docker compose down

# Остановить и удалить тома BД (осторожно!)
docker compose down -v
```

---

## Локальная разработка

### 1. Создать окружение

```bash
python3 -m venv .venv
source .venv/bin/activate

# Установить зависимости
pip install pip-tools
pip-compile requirements.in -o requirements.txt --strip-extras
pip install -r requirements.txt
```

### 2. Поднять инфраструктуру

```bash
# Только PostgreSQL и Redis (без бота)
docker compose up -d postgres redis
```

### 3. Применить миграции

```bash
cp .env.example .env   # заполни POSTGRES_* и BOT_TOKEN

ENV_FILE=.env alembic upgrade head
# или через make:
make migrate-local
```

### 4. Запустить бота

```bash
ENV_FILE=.env python -m src
# или через make:
make run-local
```

### Обновление зависимостей

Для обновления pinned `requirements.txt` после изменения `requirements.in`:

```bash
pip-compile --upgrade requirements.in -o requirements.txt --strip-extras
```

---

## Переменные окружения

Полный список с комментариями — в [.env.example](.env.example).

| Переменная | Обязательна | Описание |
|---|---|---|
| `BOT_TOKEN` | ✅ | Токен Telegram-бота |
| `POSTGRES_*` | ✅ | Хост, порт, имя БД, пользователь, пароль |
| `MODERATION_CHAT_ID` | ✅ | `chat_id` группы модерации |
| `REDIS_URL` | — | URL Redis; пусто → `MemoryStorage` |
| `CRYPTO_PAY_TOKEN` | — | API-токен `@CryptoBot`; пусто → выплаты отключены |
| `ALERT_TELEGRAM_CHAT_ID` | — | Чат системных алертов |
| `BRAND_CHANNEL_URL` | — | Ссылка на канал (кнопка в меню) |
| `BRAND_CHAT_URL` | — | Ссылка на чат/группу |
| `BRAND_PAYMENTS_URL` | — | Ссылка на страницу выплат |

---

## Скрипты обслуживания

Все скрипты запускаются из корня репозитория; берут настройки из `.env` (или `ENV_FILE`).

```bash
# Назначить роль (admin / sim_root)
python scripts/make_admin.py --telegram-id 123456789 --role admin

# Сбросить флаг is_duplicate у заявок
python scripts/reset_is_duplicate.py

# Удалить ВСЕ заявки (осторожно!)
python scripts/delete_all_submissions.py
```

---

## Тесты

```bash
# Все unit-тесты
make test

# С подробным выводом
.venv/bin/pytest -v
```

Тесты не требуют запущенной БД — сервисы тестируются через моки.

---

## Стек технологий

| Компонент | Версия |
|---|---|
| Python | 3.13 |
| aiogram | 3.22 |
| SQLAlchemy | 2.0 (async) |
| asyncpg | 0.30 |
| Alembic | 1.16 |
| FastAPI + uvicorn | 0.118 / 0.37 |
| pydantic-settings | 2.11 |
| Redis (redis-py) | 5.2 |
| PostgreSQL | 16 |
| Docker Compose | v2 |


5. Примени миграции:

```bash
export ENV_FILE=.env.local
alembic upgrade head
```

6. Запусти бота в Docker:

```bash
docker compose up -d --build bot
```

`docker-compose.yml` использует `.env.docker` автоматически.

## One-button команды

- Полный запуск в Docker:

```bash
make docker-up
```

- Локальный запуск (после `make install` и миграций):

```bash
make migrate-local
make run-local
```

