#!/usr/bin/env bash
set -eu

# ========================================
# setup-dev.sh — Инициализация dev окружения
# ========================================
# 
# Использование:  bash setup-dev.sh
# 
# Что делает:
# 1. Копирует .env.example в .env.local (если не существует)
# 2. Копирует .env.docker.example в .env.docker (если не существует)
# 3. Показывает какие переменные нужно отредактировать
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "🚀 Инициализация dev окружения"
echo "=================================================="
echo ""

# 1. Проверяем .env.local
if [ ! -f ".env.local" ]; then
    echo "📝 Создаю .env.local из .env.example..."
    cp .env.example .env.local
    echo "✅ .env.local создан"
else
    echo "✅ .env.local уже существует"
fi

# 2. Проверяем .env.docker
if [ ! -f ".env.docker" ]; then
    echo "📝 Создаю .env.docker из .env.docker.example..."
    cp .env.docker.example .env.docker
    echo "✅ .env.docker создан"
else
    echo "✅ .env.docker уже существует"
fi

echo ""
echo "=================================================="
echo "⚠️  ПЕРЕД ЗАПУСКОМ УБЕДИСЬ:"
echo "=================================================="
echo ""
echo "1️⃣  Для локальной разработки (python src):"
echo "   📄 .env.local"
echo "   • BOT_TOKEN=<твой токен>"
echo "   • POSTGRES_HOST=localhost"
echo "   • REDIS_URL= (пусто для MemoryStorage)"
echo ""
echo "2️⃣  Для Docker (docker-compose up):"
echo "   📄 .env.docker"
echo "   • BOT_TOKEN=<твой токен>"
echo "   • POSTGRES_HOST=postgres (имя service'а!)"
echo "   • REDIS_URL=redis://redis:6379/0"
echo ""
echo "⚠️  НИКОГДА не коммитай эти файлы!"
echo ""
echo "=================================================="
echo "📖 Дальше:"
echo "=================================================="
echo ""
echo "Локальная разработка (без контейнеров):"
echo "  1. pip install -r requirements.txt"
echo "  2. POSTGRES запущен локально? psql -U tgpriem -d tgpriem"
echo "  3. python -m src"
echo ""
echo "Docker (рекомендуется):"
echo "  1. docker-compose up --build"
echo "  2. docker-compose logs -f bot"
echo ""
