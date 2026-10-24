UV_IMAGE := ghcr.io/astral-sh/uv:0.9.5-python3.12-bookworm-slim
DEV_IMAGE := trip-pilot-dev

.PHONY: up down reset logs seed tools dev-image test test-integration lint ci lock

up:         ## поднять всё, как у жюри
	docker compose up --build

down:
	docker compose down

reset:      ## остановить и удалить данные БД
	docker compose down -v

logs:
	docker compose logs -f bootstrap api ui gateway

seed:       ## повторить bootstrap (идемпотентно)
	docker compose run --rm bootstrap

tools:      ## всё + pgAdmin на http://localhost:5050
	docker compose --profile tools up --build

dev-image:
	docker build -f docker/app.Dockerfile --target dev -t $(DEV_IMAGE) .

test: dev-image
	docker run --rm $(DEV_IMAGE) pytest

test-integration:  ## тесты на настоящем Postgres (поднимет db и прогонит миграции)
	docker compose --profile tests run --rm --build tests

lint: dev-image
	docker run --rm $(DEV_IMAGE) ruff check src tests migrations

ci:         ## все шаги CI, как в GitHub Actions
	sh scripts/ci.sh

lock:       ## обновить uv.lock без локально установленного uv
	docker run --rm -v "$(CURDIR):/app" -w /app $(UV_IMAGE) uv lock
