#!/bin/sh
# Все шаги CI одной командой. Этот же скрипт запускает GitHub Actions, поэтому
# «прошло локально» = «прошло бы в CI».
#
#   Git Bash, Linux, macOS:  sh scripts/ci.sh
#   PowerShell:              & "C:\Program Files\Git\bin\sh.exe" scripts/ci.sh
#
# Стек после проверки остаётся запущенным; остановить: docker compose down
set -eu

step() {
    printf '\n== %s ==\n' "$1"
}

GITLEAKS_IMAGE=zricethezav/gitleaks:v8.28.0
# В Git Bash на Windows Docker нужен путь вида C:/..., на Linux и macOS — обычный.
src=$(pwd -W 2>/dev/null || pwd)

step "Секреты: gitleaks по истории git"
# Только то, что попало в git: локальный .env с настоящим ключом в git не уходит и не мешает.
MSYS_NO_PATHCONV=1 docker run --rm -v "$src:/repo:ro" "$GITLEAKS_IMAGE" \
    git /repo --no-banner --redact --exit-code 1

step "Образ для тестов и линтера"
docker build -f docker/app.Dockerfile --target dev -t trip-pilot-dev .

step "Линтер"
docker run --rm trip-pilot-dev ruff check src tests migrations

step "Юнит-тесты"
docker run --rm trip-pilot-dev pytest

step "Конфигурация compose"
docker compose config --quiet

step "Стек, как у жюри, и /health"
docker compose up --build -d
attempt=0
until curl -fsS http://localhost:8080/health; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        echo "/health не ответил за 2 минуты"
        docker compose ps -a
        docker compose logs
        exit 1
    fi
    sleep 2
done
echo

step "Миграции: одна голова Alembic, схема совпадает с моделями"
heads=$(docker compose run --rm -T bootstrap alembic heads | grep -c '(head)' || true)
echo "голов Alembic: $heads"
if [ "$heads" -ne 1 ]; then
    echo "Ожидалась одна голова. Исправьте down_revision своей миграции (см. AGENTS.md)"
    exit 1
fi
docker compose run --rm -T bootstrap alembic check

step "Интеграционные тесты на Postgres"
docker compose --profile tests run --rm -T --build tests

printf '\n== Все шаги CI прошли ==\n'
