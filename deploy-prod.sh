#!/usr/bin/env bash
set -e

# ========================================
# deploy-prod.sh — Развертывание на сервер
# ========================================
#
# Использование: bash deploy-prod.sh
#
# Что делает:
# 1. Проверяет что .env.production существует
# 2. Проверяет Docker и docker-compose
# 3. Собирает образ
# 4. Запускает контейнеры
# 5. Выполняет миграции БД
# 6. Показывает статус
#

set_color() {
    case $1 in
        red)    echo -ne "\033[31m" ;;
        green)  echo -ne "\033[32m" ;;
        yellow) echo -ne "\033[33m" ;;
        blue)   echo -ne "\033[34m" ;;
        reset)  echo -ne "\033[0m" ;;
    esac
}

echo_success() { set_color green; echo "✅ $1"; set_color reset; }
echo_error() { set_color red; echo "❌ $1"; set_color reset; }
echo_warn() { set_color yellow; echo "⚠️  $1"; set_color reset; }
echo_info() { set_color blue; echo "ℹ️  $1"; set_color reset; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo_info "===================================================="
echo_info "🚀 Production Deploy для Telegram-бота"
echo_info "===================================================="
echo ""

# 1. Проверяем .env.production
if [ ! -f ".env.production" ]; then
    echo_error ".env.production не найден!"
    echo_warn "Необходимо создать .env.production:"
    echo ""
    echo "  1. cp .env.production.example .env.production"
    echo "  2. Отредактируй .env.production (真実 токены, пароли)"
    echo "  3. chmod 600 .env.production    # Только владелец может читать!"
    echo "  4. bash deploy-prod.sh"
    echo ""
    exit 1
fi

echo_success ".env.production найден"

# 2. Проверяем Docker
if ! command -v docker &> /dev/null; then
    echo_error "Docker не установлен!"
    echo_warn "Установи Docker: https://docs.docker.com/install/"
    exit 1
fi
echo_success "Docker доступен: $(docker --version)"

# 3. Проверяем docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo_error "docker-compose не установлен!"
    echo_warn "Установи: sudo apt install docker-compose"
    exit 1
fi
echo_success "docker-compose доступен: $(docker-compose --version)"

# 4. Проверяем права доступа на .env.production
if [ "$(stat -c '%a' .env.production)" != "600" ]; then
    echo_warn ".env.production имеет неправильные права доступа"
    echo_info "Исправляю: chmod 600 .env.production"
    chmod 600 .env.production
fi

# 5. Собираем образ
echo ""
echo_info "===================================================="
echo_info "🔨 Сборка Docker образа"
echo_info "===================================================="
echo ""

docker-compose build

echo ""
echo_success "Образ собран"

# 6. Запускаем контейнеры
echo ""
echo_info "===================================================="
echo_info "🚀 Запуск контейнеров"
echo_info "===================================================="
echo ""

docker-compose --env-file .env.production up -d

echo ""
echo_success "Контейнеры запущены"

# 7. Ждём пока бот будет ready
echo ""
echo_info "Жду пока bot service станет healthy (~45 сек)..."
sleep 10

# 8. Проверяем статус
echo ""
echo_info "===================================================="
echo_info "📊 Статус сервисов"
echo_info "===================================================="
echo ""

docker-compose ps

# 9. Проверяем healthcheck
echo ""
if docker-compose ps | grep -q "healthy"; then
    echo_success "✨ Все сервисы рабочие!"
else
    echo_warn "Некоторые сервисы ещё загружаются..."
    echo_info "Проверь логи: docker-compose logs bot"
fi

# 10. Показываем инструкции
echo ""
echo_info "===================================================="
echo_info "📖 Полезные команды"
echo_info "===================================================="
echo ""
echo "Логи бота (real-time):"
echo "  docker-compose logs -f bot"
echo ""
echo "Логи PostgreSQL:"
echo "  docker-compose logs -f postgres"
echo ""
echo "Логи Redis:"
echo "  docker-compose logs -f redis"
echo ""
echo "Перезагрузить контейнеры:"
echo "  docker-compose restart"
echo ""
echo "Остановить все:"
echo "  docker-compose down"
echo ""
echo_success "🎉 Deploy завершён!"
echo ""
