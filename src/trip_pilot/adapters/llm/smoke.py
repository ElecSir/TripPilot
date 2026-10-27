
"""Дымовая проверка подключения к LLM API."""

import asyncio
import logging
import sys
import time
from urllib.parse import urlsplit

from openai import APIStatusError
from pydantic import BaseModel

from trip_pilot.adapters.db.knowledge import EMBEDDING_DIM
from trip_pilot.adapters.llm.openai_compat import make_llm
from trip_pilot.config import get_settings
from trip_pilot.ports import LLMUnavailable

log = logging.getLogger(__name__)


class SmokeResponse(BaseModel):
    """Схема для проверки структурированного ответа."""

    ok: bool
    message: str


def print_connection_info() -> None:
    """Показать адрес сервера и названия моделей без секретов."""
    settings = get_settings()
    base_url = settings.llm_base_url

    if base_url:
        parsed = urlsplit(base_url)
        host = parsed.hostname or "не удалось определить"
        if parsed.port:
            host = f"{host}:{parsed.port}"
    else:
        host = "стандартный адрес OpenAI API"

    print(f"LLM host: {host}")
    print(f"LLM model: {settings.llm_model or 'не задана'}")
    print(f"Embeddings model: {settings.embeddings_model or 'не задана'}")


def explain_error(error: Exception) -> str:
    """Определить причину ошибки, не раскрывая ключ и тело запроса."""
    current: BaseException | None = error

    while current is not None:
        if isinstance(current, APIStatusError):
            if current.status_code == 401:
                return "401: API-ключ не принят. Проверь ключ в локальном .env."
            if current.status_code == 403:
                return "403: доступ запрещён. Проверь права ключа и модели."
            if current.status_code == 404:
                return "404: адрес API или название модели не найдены."
            if current.status_code == 429:
                return "429: превышен лимит запросов или средств."
            if current.status_code >= 500:
                return f"HTTP {current.status_code}: ошибка сервера провайдера."

        current = current.__cause__ or current.__context__

    message = str(error).casefold()

    if "не задана модель" in message:
        return "Не задано название модели в настройках .env."
    if "не удалось получить эмбеддинги" in message:
        return "Не удалось получить эмбеддинги. Проверь модель и её доступность."
    if "не удалось получить структурированный ответ" in message:
        return "Не удалось получить корректный структурированный ответ."
    if "не удалось получить ответ от llm" in message:
        return "Не удалось получить текстовый ответ. Проверь сеть и настройки API."
    if "отключена" in message or "api-ключ не задан" in message:
        return "LLM отключена: проверь LLM_API_KEY в локальном .env."

    return f"Проверка завершилась ошибкой: {type(error).__name__}."


async def run_smoke_test() -> None:
    """Проверить текстовый ответ, Pydantic-схему и размер эмбеддинга."""
    settings = get_settings()
    print_connection_info()

    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY не задан в локальном .env.")

    llm = make_llm(settings)

    # 1. Обычный текстовый запрос.
    started = time.perf_counter()
    answer = await llm.complete(
        [
            {
                "role": "user",
                "content": "Ответь одним словом: OK",
            }
        ]
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    if not answer.strip():
        raise RuntimeError("Модель вернула пустой текстовый ответ.")

    print(f"complete: ok ({elapsed_ms} мс)")

    # 2. Ответ, который должен соответствовать Pydantic-схеме.
    structured = await llm.structured(
        [
            {
                "role": "user",
                "content": (
                    "Заполни JSON: ok = true, message = 'Подключение работает'."
                ),
            }
        ],
        SmokeResponse,
    )

    if not structured.ok or not structured.message.strip():
        raise RuntimeError("Структурированный ответ содержит неверные значения.")

    print("structured: ok")

    # 3. Эмбеддинг и проверка размерности, принятой в базе данных.
    vectors = await llm.embed(["Проверка подключения к TripPilot."])

    if len(vectors) != 1:
        raise RuntimeError(
            f"Ожидался один эмбеддинг, получено: {len(vectors)}."
        )

    dimension = len(vectors[0])

    if dimension != EMBEDDING_DIM:
        raise RuntimeError(
            f"Размерность эмбеддинга — {dimension}, "
            f"а в БД ожидается {EMBEDDING_DIM}."
        )

    print(f"embed: ok, размерность {dimension}")
    print("Все проверки LLM успешно пройдены.")


def main() -> int:
    """Запустить проверки и вернуть код завершения."""
    logging.disable(logging.CRITICAL)

    try:
        asyncio.run(run_smoke_test())
    except Exception as error:
        print(explain_error(error), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
