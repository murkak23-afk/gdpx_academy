# Media Content Acceptance System

Проект Telegram-бота на `aiogram 3.x` с асинхронным стеком и PostgreSQL.

## Быстрый старт

1. Создай отдельные env-файлы:

```bash
cp .env.local.example .env.local
cp .env.docker.example .env.docker
```

2. Запусти PostgreSQL в Docker:

```bash
docker compose up -d postgres
```

3. Установи зависимости локально (для запуска миграций):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. Примени миграции:

```bash
export ENV_FILE=.env.local
alembic upgrade head
```

5. Запусти бота в Docker:

```bash
docker compose up -d --build bot
```

`docker-compose.yml` использует `.env.docker` автоматически.

## Полезные команды

- Создать новую миграцию:

```bash
export ENV_FILE=.env.local
alembic revision --autogenerate -m "описание_изменений"
```

- Откатить последнюю миграцию:

```bash
export ENV_FILE=.env.local
alembic downgrade -1
```

- Посмотреть логи бота:

```bash
docker compose logs -f bot
```

- Назначить пользователя админом:

```bash
export ENV_FILE=.env.local
python -m scripts.make_admin --telegram-id 123456789
```
