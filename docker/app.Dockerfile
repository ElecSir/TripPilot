# Один образ на три роли: api (по умолчанию), ui и bootstrap (см. docker-compose.yml).
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
# Сначала только зависимости: этот слой кэшируется, пока не меняется uv.lock.
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Образ для тестов и линтера: make test / make lint.
FROM build AS dev
RUN uv sync --frozen
COPY tests ./tests
COPY migrations ./migrations
COPY data ./data
CMD ["pytest"]

FROM ${PYTHON_IMAGE} AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY alembic.ini ./
COPY migrations ./migrations
COPY data ./data
COPY .streamlit ./.streamlit
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER app
EXPOSE 8000
CMD ["uvicorn", "trip_pilot.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
