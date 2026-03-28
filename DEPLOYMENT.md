# 🚀 PRODUCTION DEPLOYMENT GUIDE
## Telegram Bot + Docker на Ubuntu сервере

---

## ЭТАП 1: Подготовка сервера (ОДИН РАЗ)

### 1.1 Обновить систему
```bash
sudo apt-get update && sudo apt-get upgrade -y
```

### 1.2 Установить Docker
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Добавить текущего пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker
```

**Проверка:**
```bash
docker --version
docker run hello-world
```

### 1.3 Установить docker-compose
```bash
sudo apt-get install -y docker-compose
docker-compose --version
```

### 1.4 Установить Git
```bash
sudo apt-get install -y git
git --version
```

---

## ЭТАП 2: Клонирование проекта

### 2.1 Выбрать папку для проекта
```bash
# Рекомендуется /opt/ для production приложений
cd /opt
# ИЛИ в домашней папке
cd ~
```

### 2.2 Клонировать репозиторий
```bash
git clone https://github.com/YOUR_USERNAME/gdpx_academy.git
cd gdpx_academy
```

Или скопировать файлы вручную с локальной машины:
```bash
# На вашей локальной машине
scp -r ./* user@server_ip:/opt/gdpx_academy/
```

---

## ЭТАП 3: Настройка конфигурации

### 3.1 Создать .env.production
```bash
cp .env.production.example .env.production
nano .env.production  # Или vim
```

**Отредактировать ОБЯЗАТЕЛЬНО:**
```bash
# 1. Новый BOT_TOKEN
BOT_TOKEN=<реальный_токен_от_BotFather>

# 2. НОВЫЙ сильный пароль для БД!
POSTGRES_PASSWORD=<сгенерированный_пароль_32_символа>
# Пример генерации:
# openssl rand -base64 32

# 3. Реальные ID чатов
MODERATION_CHAT_ID=-<ID чата>
ALERT_TELEGRAM_CHAT_ID=-<ID чата>  # опционально

# 4. Реальные ссылки бренда
BRAND_CHANNEL_URL=https://t.me/...
BRAND_CHAT_URL=https://t.me/+...
```

### 3.2 Защитить файл
```bash
chmod 600 .env.production
ls -la .env.production  # Проверить права -rw-------
```

### 3.3 Настроить .dockerignore (уже готов)
```bash
cat .dockerignore  # Должен исключать: .venv, .git, .env*, logs
```

---

## ЭТАП 4: Запуск контейнеров

### 4.1 Собрать образ
```bash
docker-compose build
```

**Если ошибка с кэшем - очистить:**
```bash
docker-compose build --no-cache
```

### 4.2 Запустить контейнеры (в фоне)
```bash
docker-compose up -d
```

**Проверка статуса:**
```bash
docker-compose ps
```

Должны быть 3 контейнера:
- ✅ tgpriem_postgres (healthy)
- ✅ tgpriem_redis (healthy)
- ✅ tgpriem_bot (healthy, после ~45 сек)

### 4.3 Проверить логи
```bash
# Логи всех сервисов
docker-compose logs

# Логи только бота (последние 100 строк)
docker-compose logs -n 100 bot

# Логи в реальном времени
docker-compose logs -f bot

# Логи Postgres
docker-compose logs -f postgres
```

---

## ЭТАП 5: Верификация работоспособности

### 5.1 Health Check
```bash
# Бот должен ответить 200 OK
curl -s http://localhost:8000/health | jq .

# Или просто
curl http://localhost:8000/health
```

### 5.2 Проверить подключение к БД
```bash
docker-compose exec postgres psql -U tgpriem -d tgpriem -c "SELECT 1"
# Должен вернуть: 1
```

### 5.3 Проверить Redis
```bash
docker-compose exec redis redis-cli ping
# Должен вернуть: PONG
```

### 5.4 Проверить миграции
```bash
docker-compose logs bot | grep "Applying"
# Должны пройти миграции в начале логов
```

---

## ЭТАП 6: Автозапуск (чтобы боту вернулся после reboot)

### 6.1 Создать systemd сервис
```bash
sudo nano /etc/systemd/system/telegram-bot.service
```

Вставить:
```ini
[Unit]
Description=Telegram Bot Service
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/gdpx_academy

# Запуск
ExecStart=/usr/bin/docker-compose up -d

# Остановка
ExecStop=/usr/bin/docker-compose down

Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

### 6.2 Активировать сервис
```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot.service
sudo systemctl start telegram-bot.service
sudo systemctl status telegram-bot.service
```

**Проверить при перезагрузке:**
```bash
sudo reboot
# После перезагрузки
docker-compose ps
```

---

## ЭТАП 7: Мониторинг и обслуживание

### 7.1 Просмотр логов
```bash
# Последние логи
docker-compose logs -n 50 bot

# Логи за последний час
docker-compose logs --since 1h bot

# Следить за логами (Ctrl+C для выхода)
docker-compose logs -f bot
```

### 7.2 Перезагрузить только бота (без БД)
```bash
docker-compose restart bot
```

### 7.3 Остановить все контейнеры
```bash
docker-compose stop
```

### 7.4 Полная очистка (ВНИМАНИЕ: удаляет БД!)
```bash
docker-compose down -v  # -v удаляет volumes (БД!)
```

### 7.5 Backup БД
```bash
docker-compose exec postgres pg_dump -U tgpriem tgpriem > backup_$(date +%Y%m%d_%H%M%S).sql
```

### 7.6 Restore БД
```bash
docker-compose exec -T postgres psql -U tgpriem tgpriem < backup_20260327_120000.sql
```

---

## ЭТАП 8: Обновление приложения

### 8.1 Получить новыйкод
```bash
cd /opt/gdpx_academy
git pull origin main
```

### 8.2 Пересобрать и перезагрузить
```bash
docker-compose build --no-cache
docker-compose up -d
```

### 8.3 Проверить обновление
```bash
docker-compose logs -n 30 bot | grep -E "Applying|Starting"
```

---

## 🆘 TROUBLESHOOTING

### Проблема: Bot не подключается к PostgreSQL
```bash
docker-compose logs bot | grep "ERRO"
docker-compose restart postgres
docker-compose up -d bot
```

### Проблема: Контейнер unhealthy
```bash
docker-compose ps  # Проверить статус
docker-compose logs <container_name>
docker-compose restart <container_name>
```

### Проблема: Дисковое пространство закончилось
```bash
# Очистить неиспользуемые образы и контейнеры
docker system prune -a

# Проверить размер volumes
docker volume ls
docker volume inspect <volume_name>
```

### Проблема: Логи растут слишком быстро
```bash
# Ограничить размер логов в docker-compose.yml
# Добавить в bot service:
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

---

## 📊 Полезные команды

```bash
# Статус всех сервисов
docker-compose ps

# Очистить неиспользуемые ресурсы Docker
docker system prune

# Просмотр использования ресурсов
docker stats

# Все работающие контейнеры
docker ps

# Все образы
docker images

# Удалить образ
docker rmi <image_id>

# Запустить команду внутри контейнера
docker-compose exec bot bash
docker-compose exec postgres bash
docker-compose exec redis bash
```

---

## ✅ ФИНАЛЬНЫЙ CHECKLIST

- [ ] Docker установлен (`docker --version`)
- [ ] docker-compose установлен (`docker-compose --version`)
- [ ] Проект клонирован в `/opt/gdpx_academy`
- [ ] `.env.production` создан и заполнен реальными значениями
- [ ] Права доступа: `chmod 600 .env.production`
- [ ] Образ собран: `docker-compose build`
- [ ] Контейнеры запущены: `docker-compose up -d`
- [ ] Все healthchecks зелёные: `docker-compose ps`
- [ ] Health endpoint работает: `curl http://localhost:8000/health`
- [ ] Логи БД чистые (нет ERRORов)
- [ ] Systemd сервис создан (опционально, но рекомендуется)

---

## 🔗 Ссылки

- Docker docs: https://docs.docker.com/
- docker-compose docs: https://docs.docker.com/compose/
- PostgreSQL docs: https://www.postgresql.org/docs/
- Redis docs: https://redis.io/docs/

