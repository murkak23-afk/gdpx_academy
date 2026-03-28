# 🎯 ИТОГОВАЯ ИНСТРУКЦИЯ ДЕПЛОЯ: Готов к Production

Это **финальная инструкция** на основе полного аудита проекта. Скопируйте  команды в терминал **по порядку**.

---

## БЫСТРЫЙ СТАРТ (5-7 минут)

### Шаг 1️⃣: Подготовка ОС (на свежем Ubuntu 22.04)
```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y curl gnupg lsb-release git
```

### Шаг 2️⃣: Установка Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Проверка
docker --version
docker run hello-world
```

### Шаг 3️⃣: Клонирование проекта
```bash
cd /opt  # Или выбери свою папку
git clone https://github.com/YOUR_REPO/gdpx_academy.git
cd gdpx_academy
```

### Шаг 4️⃣: Конфигурация (.env.docker)
```bash
nano .env.docker  # Или используйте vim/vi
```

**Обязательно заполните эти переменные:**

| Переменная | Значение | Пример |
|-----------|----------|--------|
| `BOT_TOKEN` | Token от @BotFather в Telegram | `123456789:ABCdefGHIjklmnoPQRstuvWXYZ_abc` |
| `POSTGRES_PASSWORD` | Надёжный пароль БД | `SuperSecure_Pass123!@` |
| `CRYPTO_PAY_TOKEN` | Token от CryptoBot | `YOUR_CRYPTOBOT_TOKEN` |
| `MODERATION_CHAT_ID` | ID чата модерации | `-1001234567890` |
| `ALERT_TELEGRAM_CHAT_ID` | ID чата для алертов | `-1001234567890` |
| `POSTGRES_USER` | Пользователь БД | `gdpx_user` |
| `POSTGRES_DB` | Имя БД | `gdpx_academy` |

**Как найти Chat ID:**
```bash
# Временно запустите бот с другим token, отправьте сообщение, и посмотрите логи
# Или используйте @userinfobot в Telegram
```

### Шаг 5️⃣: Запуск приложения
```bash
docker compose up -d
```

### Шаг 6️⃣: Проверка статуса (ждите 30 сек)
```bash
docker compose ps

# Должны быть "Up" (зелёные)
# tgpriem_postgres: healthy
# tgpriem_redis: healthy
# tgpriem_bot: Up
```

### Шаг 7️⃣: Проверка здоровья приложения
```bash
curl http://localhost:8000/health
# Должно вернуть: {"status":"ok"}

curl http://localhost:8000/health/ready
# Должно вернуть: {"status":"ready","checks":{"database":"ok","cryptobot":"ok"}}
```

### Шаг 8️⃣: Проверка логов
```bash
docker compose logs bot | tail -30

# Должны увидеть:
# "Старт процесса (бот + HTTP)"
# Без ERROR или CRITICAL
```

### Шаг 9️⃣: Финальная проверка в Telegram
1. Откройте Telegram
2. Найдите вашего бота (по username)
3. Отправьте `/start`
4. Должна появиться главное меню

✅ **Если всё работает - готово к production!**

---

## ДОПОЛНИТЕЛЬНАЯ КОНФИГУРАЦИЯ (опционально)

### Настройка systemd для автозагрузки при перезагрузке сервера

Создайте файл `/etc/systemd/system/gdpx-bot.service`:
```bash
sudo tee /etc/systemd/system/gdpx-bot.service > /dev/null << 'EOF'
[Unit]
Description=GDPX Academy Telegram Bot
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/gdpx_academy
# ИЛИ если в домашней папке:
# WorkingDirectory=/home/your_user/gdpx_academy

ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
```

Активируйте:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gdpx-bot.service
sudo systemctl start gdpx-bot.service

# Проверьте
sudo systemctl status gdpx-bot.service
```

---

## КОМАНДЫ УПРАВЛЕНИЯ

### Остановить контейнеры (данные останутся в БД)
```bash
docker compose down
```

### Перезагрузить
```bash
docker compose restart
```

### Обновить код и перезапустить
```bash
git pull
docker compose build --no-cache
docker compose up -d
```

### Посмотреть логи в реальном времени (live)
```bash
docker compose logs -f bot
# Выход: Ctrl+C
```

### Проверить размер использованного дискового пространства
```bash
docker system df
```

### Очистить неиспользуемые Docker образы
```bash
docker system prune --all --volumes
```

---

## РЕЗЕРВНОЕ КОПИРОВАНИЕ

### Создать backup БД (один раз)
```bash
docker exec tgpriem_postgres pg_dump -U gdpx_user -Fc gdpx_academy > backup_$(date +%Y%m%d_%H%M%S).dump
ls -lh backup_*.dump
```

### Восстановить БД из backup
```bash
docker exec -i tgpriem_postgres pg_restore -U gdpx_user -d gdpx_academy < backup_YYYYMMDD_HHMMSS.dump
```

### Автоматический ежедневный backup (cron)
```bash
# Откройте редактор crontab
sudo crontab -e

# Добавьте эту строку (пример: 2:00 AM каждый день):
0 2 * * * cd /opt/gdpx_academy && docker exec tgpriem_postgres pg_dump -U gdpx_user -Fc gdpx_academy > /backups/backup_$(date +\%Y\%m\%d_\%H\%M\%S).dump 2>&1 | logger

# Создайте папку для backup
sudo mkdir -p /backups
sudo chmod 755 /backups
```

---

## РЕШЕНИЕ ПРОБЛЕМ

### ❌ Контейнер postgres не запускается (status: exited)
```bash
# 1. Проверьте ошибки
docker compose logs postgres

# 2. Проверьте права на volumes
ls -la ./postgres_data  # Должны быть права 755

# 3. Удалите старые данные (⚠️ потеря всех данных!)
docker volume rm gdpx_academy_postgres_data
docker compose up -d postgres

# 4. Проверьте .env.docker
cat .env.docker | grep POSTGRES
```

### ❌ Бот говорит "ошибка API" при создании чека
```bash
# 1. Проверьте CRYPTO_PAY_TOKEN в .env.docker
grep CRYPTO_PAY_TOKEN .env.docker

# 2. Если видите "NOT_ENOUGH_COINS" - пополните баланс CryptoBot

# 3. Проверьте логи
docker compose logs bot | grep -i crypto
```

### ❌ Бот не отвечает в Telegram
```bash
# 1. Проверьте, запущен ли контейнер
docker compose ps bot

# 2. Проверьте token правильный
docker compose logs bot | grep "BOT_TOKEN"

# 3. Проверьте интернет
ping 8.8.8.8

# 4. Перезагрузите бот контейнер
docker compose restart bot
```

### ❌ Высокое использование памяти/диска
```bash
# Посмотрите статистику Docker
docker stats

# Очистите неиспользуемые образы (безопасно)
docker image prune -a

# Очистите volumes (⚠️ потеря данных FSM/cache)
docker volume prune
```

---

## МОНИТОРИНГ В PRODUCTION

### Проверка здоровья каждый час (через cron + curl)
```bash
# -или- используйте Telegram уведомления через аренду монитора:
sudo tee /usr/local/bin/check-gdpx-bot.sh > /dev/null << 'EOF'
#!/bin/bash
HEALTH=$(curl -s http://localhost:8000/health/ready | grep -o '"status":"ready"')
if [ -z "$HEALTH" ]; then
  echo "⚠️ GDPX Bot is DOWN! Check now." | mail -s "ALERT: GDPX Bot" admin@example.com
  # Альтернатива: отправить в Telegram
fi
EOF

sudo chmod +x /usr/local/bin/check-gdpx-bot.sh

# Добавьте в crontab
sudo crontab -e
# 0 * * * * /usr/local/bin/check-gdpx-bot.sh
```

### Включение логов в systemd journal
```bash
# Просмотр логов сервиса
sudo journalctl -u gdpx-bot.service -f

# Последние 100 строк
sudo journalctl -u gdpx-bot.service -n 100
```

---

## КОНТРОЛЬНЫЙ ЛИСТ ДЛЯ PRODUCTION

- [ ] Ubuntu 22.04 LTS установлена
- [ ] Docker & docker-compose установлены
- [ ] Проект клонирован в `/opt/gdpx_academy` (или другую папку)
- [ ] `.env.docker` заполнен всеми обязательными переменными
  - [ ] BOT_TOKEN (от @BotFather)
  - [ ] POSTGRES_PASSWORD (сложный пароль)
  - [ ] CRYPTO_PAY_TOKEN (от CryptoBot)
  - [ ] MODERATION_CHAT_ID (правильный ID)
  - [ ] Другие переменные
- [ ] `docker compose up -d` выполнена успешно
- [ ] `docker compose ps` показывает все контейнеры "Up"
- [ ] `/health` endpoint возвращает успех
- [ ] `/health/ready` endpoint показывает "ready"
- [ ] Логи бота не содержат ERROR (проверено `docker compose logs bot`)
- [ ] Бот отвечает на `/start` в Telegram ✅
- [ ] Systemd сервис`gdpx-bot.service` настроен и работает
- [ ] Резервное копирование настроено (cron job)
- [ ] Firewall / Security Group разрешает порт 8000 (если нужен)

---

## ФИНАЛЬНЫЕ СОВЕТЫ МЕНТОРСТВА

### 🔒 Безопасность
1. **Никогда не коммитьте `.env.docker`** в git (добавьте в `.gitignore`)
2. **Используйте сильные пароли** для POSTGRES_PASSWORD
3. **Ограничьте доступ** к папке проекта (`chmod 700` если нужно)
4. **Включите SSH ключи** вместо паролей на сервере
5. **Используйте firewall** (ufw) для ограничения портов

### 📊 Масштабирование
1. **PostgreSQL** автоматически масштабируется через connection pooling
2. **Redis** хранит FSM состояния (не нужен для MemoryStorage)
3. **Используйте nginx** как reverse proxy перед этим приложением

### 🧪 Тестирование перед production
```bash
# Запустите тесты
pytest tests/

# Проверьте линтинг
ruff check .

# Соберите образ и проверьте size
docker build -t gdpx:test . && docker images | grep gdpx
```

### 📈 Мониторинг и логирование
- Настройте **Prometheus** + **Grafana** для long-term метрик
- Используйте **ELK Stack** (Elasticsearch, Logstash, Kibana) для логов
- Интегрируйте **Sentry** для отслеживания ошибок в Python коде

---

## 📞 Что делать если что-то не работает?

1. **Проверьте логи:**
   ```bash
   docker compose logs -f --tail=100
   ```

2. **Проверьте ресурсы:**
   ```bash
   docker stats
   ```

3. **Перезагрузитесь:**
   ```bash
   docker compose down && docker compose up -d
   ```

4. **Проверьте конфигурацию:**
   ```bash
   cat .env.docker | grep -E "BOT_|POSTGRES_|CRYPTO_"
   ```

5. **Если не помогает - создайте GitHub Issue** с логами!

---

**Дата обновления**: March 28, 2026  
**Статус**: ✅ Ready for Production  
**Версия приложения**: 1.0
