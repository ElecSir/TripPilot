"""Настройки: пустые переменные из .env.example означают значения по умолчанию."""

import pytest

from trip_pilot.config import Settings

EMPTY = (
    "LOG_LEVEL", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "EMBEDDINGS_MODEL",
    "LLM_MAX_CONCURRENCY", "LLM_STEP_TIMEOUT", "DEMO_MODE",
)


def test_empty_variables_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in EMPTY:
        monkeypatch.setenv(name, "")

    settings = Settings(_env_file=None)

    assert settings.log_level == "INFO"
    assert settings.llm_max_concurrency == 8
    assert settings.llm_step_timeout == 15.0
    assert settings.llm_api_key is None
    assert not settings.llm_enabled  # пустой ключ — режим без LLM, как у жюри без secrets


def test_filled_variables_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_STEP_TIMEOUT", "30")
    monkeypatch.setenv("LLM_MODEL", "dots-studio/dots-3-note-preview:free")

    settings = Settings(_env_file=None)

    assert settings.llm_step_timeout == 30.0
    assert settings.llm_model == "dots-studio/dots-3-note-preview:free"
