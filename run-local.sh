#!/usr/bin/env bash
set -e

# ========================================
# run-local.sh — Локальный запуск Docker
# ========================================
#
# Использование: bash run-local.sh
#
# Что делает:
# 1. Проверяет что .env.docker существует
# 2. Собирает образ (если не собран)
# 3. Запускает docker-compose up
# 4. Показывает логи в реальном времени
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
echo_info "🚀 Локальный запуск Telegram-бота (Docker)"
echo_info "===================================================="
echo ""

# 1. Проверяем .env.docker
if [ ! -f ".env.docker" ]; then
    echo_error ".env.docker не найден!"
    echo_warn "Создаю из .env.docker.example..."
    cp .env.docker.example .env.docker
    echo_info "Отредактируй .env.docker если нужно, потом запусти заново"
    exit 1
fi

echo_success ".env.docker найден"

# 2. Проверяем Docker
if ! command -v docker &> /dev/null; then
    echo_error "Docker не установлен!"
    echo_warn "Установи Docker: https://docs.docker.com/install/"
    exit 1
fi

echo_success "Docker доступен"

# 3. Собираем образ (если не собран)
echo ""
echo_info "===================================================="
echo_info "🔨 Проверка Docker образа"
echo_info "===================================================="
echo ""

if docker images | grep -q "gdpx_academy_bot"; then
    echo_info "Образ уже существует"
    read -p "Пересобрать? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker-compose build
    fi
else
    echo_info "Образ не найден, собираю..."
    docker-compose build
fi

echo ""
echo_success "Образ готов"

# 4. Запускаем docker-compose
echo ""
echo_info "===================================================="
echo_info "🚀 Запуск контейнеров"
echo_info "===================================================="
echo ""

docker-compose up --build

# 5. cleanup на ctrl+c
trap "echo ''; echo_info 'Остановка контейнеров...'; docker-compose down; echo_success 'Контейнеры остановлены'" EXIT

