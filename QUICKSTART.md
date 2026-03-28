# 🚀 QUICK START — Развертывание на сервер

## ЧТО УЖЕ ГОТОВО ✅

```
✅ Dockerfile           → Python 3.12-slim, оптимизирован
✅ docker-compose.yml   → PostgreSQL 16 + Redis 7 + Bot
✅ .env.local           → Для локальной разработки  
✅ .env.docker          → Для локального Docker тестирования
✅ .env.production.example → Шаблон для сервера
✅ .dockerignore        → Оптимальный размер образа
✅ docker-entrypoint.sh → Миграции БД перед стартом
✅ setup-dev.sh         → Инициализация dev окружения
✅ run-local.sh         → Локальный запуск Docker
✅ deploy-prod.sh       → Автоматизированный deployment
✅ Миграции Alembic     → 25+ версий схемы БД
✅ Config Pydantic      → Type-safe переменные окружения
```

---

## НА ЛИНУКС СЕРВЕРЕ (Ubuntu 20.04+)

### Шаг 1: Установить Docker (5 минут)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker --version
```

### Шаг 2: Клонировать проект
```bash
cd /opt
sudo git clone https://github.com/YOUR_REPO/gdpx_academy.git
cd gdpx_academy
sudo chown -R $USER:$USER .
```

### Шаг 3: Создать .env.production
```bash
cp .env.production.example .env.production
nano .env.production
# ↑ Отредактировать:
#   BOT_TOKEN = реальный токен
#   POSTGRES_PASSWORD = сильный пароль (32 символа)
#   MODERATION_CHAT_ID = реальный ID
chmod 600 .env.production
```

### Шаг 4: Запустить (3 команды!)
```bash
docker-compose build          # Собрать образ (~2 мин)
docker-compose up -d          # Запустить контейнеры
docker-compose ps             # Проверить статус
```

### Шаг 5: Проверить работу
```bash
curl http://localhost:8000/health          # Health check
docker-compose logs -f bot                 # Логи бота
docker-compose exec postgres psql -U tgpriem -c "SELECT 1"  # БД live
```

### Шаг 6: Автозапуск при reboot (опционально)
```bash
sudo bash setup-systemd.sh    # Создать systemd сервис
sudo systemctl status telegram-bot
```

---

## СТРУКТУРА ФАЙЛОВ

```
.
├── Dockerfile                 # Образ Python 3.12-slim
├── docker-compose.yml         # Оркестрация (postgres + redis + bot)
├── docker-entrypoint.sh       # Миграции перед стартом
├── .dockerignore              # Исключения при сборке
├── requirements.txt           # Python зависимости
│
├── .env.local                 # Локальная разработка (НЕ в git)
├── .env.docker                # Docker локально (НЕ в git)
├── .env.example               # Шаблон для разработки
├── .env.docker.example        # Шаблон для Docker
├── .env.production.example    # Шаблон для production
│
├── setup-dev.sh               # 🔧 Инициализация dev
├── run-local.sh               # 🚀 Локальный Docker
├── deploy-prod.sh             # 🌐 Production deploy
├── DEPLOYMENT.md              # 📖 Полный gide
│
├── src/                       # Приложение
│   ├── __main__.py            # Entry point
│   ├── core/
│   │   ├── config.py          # Pydantic Settings
│   │   ├── bot.py             # aiogram бот
│   │   └── app.py             # FastAPI приложение
│   └── ...
│
├── alembic/                   # Миграции БД
│   └── versions/              # 25+ миграций
│
└── tests/                     # Тесты
```

---

## ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ

### 🔴 КРИТИЧНЫ (обязательно заполнить)

| Переменная | Где | Значение |
|-----------|-----|----------|
| `BOT_TOKEN` | .env.production | От BotFather |
| `POSTGRES_PASSWORD` | .env.production | **НОВЫЙ** сильный пароль |
| `MODERATION_CHAT_ID` | .env.production | ID чата в Telegram |

### 🟡 РЕКОМЕНДУЕТСЯ

| Переменная | Где | Значение |
|-----------|-----|----------|
| `ALERT_TELEGRAM_CHAT_ID` | .env.production | ID чата для ошибок |
| `BRAND_CHANNEL_URL` | .env.production | Ссылка t.me/... |
| `BRAND_CHAT_URL` | .env.production | Ссылка t.me/+... |

### 🟢 АВТОМАТИЧЕСКИЕ (Docker)

```
POSTGRES_HOST=postgres              # DNS в docker-compose
POSTGRES_PORT=5432
POSTGRES_DB=tgpriem
REDIS_URL=redis://redis:6379/0      # DNS в docker-compose
HTTP_HOST=0.0.0.0                   # Слушать все интерфейсы
HTTP_PORT=8000
```

---

## ИСПОЛЬЗОВАНИЕ

### Локальная разработка (без контейнеров)
```bash
# Установить зависимости
pip install -r requirements.txt

# Запустить бота (нужен локальный PostgreSQL!)
python -m src
```

### Локальное Docker тестирование
```bash
bash run-local.sh
# ИЛИ вручную:
docker-compose build
docker-compose up -d
docker-compose logs -f
```

### Production сервер
```bash
bash deploy-prod.sh
# ИЛИ вручную: смотри DEPLOYMENT.md
```

---

## ЛОГИ И DEBUG

```bash
# Все логи
docker-compose logs

# Логи только бота
docker-compose logs bot

# Посмотреть в реальном времени
docker-compose logs -f bot

# Последние 100 строк
docker-compose logs -n 100 bot

# Логи за последний час
docker-compose logs --since 1h bot
```

---

## ОБНОВЛЕНИЕ

```bash
cd /opt/gdpx_academy
git pull
docker-compose build --no-cache
docker-compose up -d
```

---

## ПРОБЛЕМЫ?

1. **Bot unhealthy** → `docker-compose logs bot`
2. **Не подключается к БД** → `docker-compose restart postgres`
3. **Нет Redis** → `docker-compose restart redis`
4. **Логи не видны** → `docker-compose up` (без -d, в foreground)

Смотри `DEPLOYMENT.md` для подробного troubleshooting.

---

## ✨ ГОТОВО!

Проект полностью настроен для production.
- Dockerfile оптимален (python:3.12-slim)
- docker-compose с healthchecks
- Миграции работают автоматически
- Логи сохраняются
- Безопасное хранение .env файлов

Теперь просто копируй на сервер и запускай! 🚀
