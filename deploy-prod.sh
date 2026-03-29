#!/usr/bin/env bash
set -e

# ========================================
# deploy-prod.sh — Развертывание на сервер
# ========================================

GREEN='\033[32m' RED='\033[31m' YELLOW='\033[33m' BLUE='\033[34m' NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${NC}"; }
err()  { echo -e "${RED}❌ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
info() { echo -e "${BLUE}ℹ️  $1${NC}"; }

cd "$(dirname "${BASH_SOURCE[0]}")"

info "🚀 GDPX Academy — Production Deploy"
echo ""

# 1. .env
if [ ! -f ".env" ]; then
    err ".env не найден!"
    warn "cp .env.example .env && nano .env"
    exit 1
fi
ok ".env найден"

# 2. Docker
if ! command -v docker &>/dev/null; then
    err "Docker не установлен! https://docs.docker.com/install/"
    exit 1
fi
ok "Docker: $(docker --version | head -1)"

if ! docker compose version &>/dev/null; then
    err "docker compose (v2) не доступен!"
    exit 1
fi
ok "docker compose: $(docker compose version --short)"

# 3. Права .env
PERMS=$(stat -c '%a' .env 2>/dev/null || stat -f '%A' .env 2>/dev/null)
if [ "$PERMS" != "600" ]; then
    chmod 600 .env
    warn ".env права исправлены → 600"
fi

# 4. Сборка и запуск
echo ""
info "🔨 Сборка образов..."
docker compose build --pull

echo ""
info "🚀 Запуск контейнеров..."
docker compose up -d

echo ""
info "⏳ Ожидание healthcheck (~30 сек)..."
sleep 10

# 5. Статус
echo ""
docker compose ps
echo ""

if docker compose ps | grep -q "healthy"; then
    ok "✨ Все сервисы работают!"
else
    warn "Некоторые сервисы загружаются: docker compose logs -f bot"
fi

echo ""
info "Полезные команды:"
echo "  docker compose logs -f bot      — логи бота"
echo "  docker compose restart bot      — перезапуск бота"
echo "  docker compose down             — остановка"
echo "  docker compose up -d --build    — пересборка"
echo ""
ok "🎉 Deploy завершён!"
