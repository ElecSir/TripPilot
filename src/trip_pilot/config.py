from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Вся конфигурация берётся из переменных окружения (см. .env.example)."""

    # Пустая переменная = значение по умолчанию: в .env.example все значения пустые
    # (так просят организаторы), и `cp .env.example .env` не должен ломать запуск.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # В Docker собирается в docker-compose.yml из POSTGRES_*; значение ниже — для запуска
    # вне Docker с локальным override (порт БД 5433).
    database_url: str = "postgresql+asyncpg://trip:trip@localhost:5433/trip"
    api_url: str = "http://localhost:8000"
    data_dir: Path = Path("data")
    log_level: str = "INFO"

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    embeddings_model: str | None = None
    llm_max_concurrency: int = 8
    # Сколько секунд агент ждёт модель на одном шаге (понимание, объяснения); дольше — правила.
    llm_step_timeout: float = 15.0
    demo_mode: str = "auto"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
