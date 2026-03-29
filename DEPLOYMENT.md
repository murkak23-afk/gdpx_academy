# GDPX Academy — Деплой на сервер

## Требования

- Ubuntu 22.04+ / Debian 12+
- Docker Engine 24+ с docker compose v2
- 1 GB RAM, 10 GB диск

## Быстрый старт (5 минут)

```bash
# 1. Клонировать / скопировать проект
git clone <repo> /opt/gdpx_academy && cd /opt/gdpx_academy

# 2. Создать .env из шаблона
cp .env.example .env
nano .env          # Вписать BOT_TOKEN, POSTGRES_PASSWORD, MODERATION_CHAT_ID
chmod 600 .env

# 3. Запустить
bash deploy-prod.sh
```

**Готово.** Бот работает. Postgres, Redis и бот поднимаются автоматически и перезапускаются при крашах.

## Переменные .env (обязательные)

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен от @BotFather |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL (рандомный, >20 символов) |
| `MODERATION_CHAT_ID` | ID чата модерации (числовой, с минусом) |

Остальные переменные — см. `.env.example`.

## Повседневные команды

```bash
cd /opt/gdpx_academy

# Логи бота (live)
docker compose logs -f bot

# Перезапуск после изменения кода
docker compose up -d --build

# Остановка
docker compose down

# Только перезапуск бота (без пересборки)
docker compose restart bot

# Миграция БД (выполняется автоматически при старте)
docker compose exec bot alembic upgrade head

# Бэкап PostgreSQL
docker compose exec postgres pg_dump -U gdpx gdpx | gzip > backup_$(date +%F).sql.gz
```

## Обновление кода

```bash
cd /opt/gdpx_academy
git pull
docker compose up -d --build
# Миграции применяются автоматически через docker-entrypoint.sh
```

## Архитектура контейнеров

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  gdpx_bot   │────▶│gdpx_postgres│     │ gdpx_redis  │
│ Python 3.13 │     │ PG 16 Alpine│     │ Redis 7 Alp │
│ :8000/health│     │ :5432 (local)│     │ :6379 (local)│
└─────────────┘     └─────────────┘     └─────────────┘
```

- Порты привязаны к `127.0.0.1` — не торчат наружу
- `restart: unless-stopped` — автоперезапуск
- Healthcheck на каждом контейнере
- Миграции Alembic при каждом старте бота
- Данные PostgreSQL в Docker volume `postgres_data`

## Установка Docker (если не установлен)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# перелогиниться
```

