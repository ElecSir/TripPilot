"""Адаптер для OpenAI-совместимых LLM API."""

import asyncio
import json
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from trip_pilot.config import Settings
from trip_pilot.ports import LLM, ChatMessages, LLMUnavailable

T = TypeVar("T", bound=BaseModel)


def _strip_json_fence(raw: str) -> str:
    """Удалить Markdown-обёртку вокруг JSON, если она есть."""
    stripped = raw.strip()

    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()

    if lines and lines[0].startswith("```"):
        lines = lines[1:]

    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    return "\n".join(lines).strip()

def _is_retryable(error: BaseException) -> bool:
    """Повторять только сетевые ошибки, таймауты и HTTP 429/5xx."""
    if isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True

    return isinstance(error, APIStatusError) and error.status_code >= 500


class NullLLM:
    """Безопасная заглушка, если API-ключ не настроен."""

    enabled = False

    async def complete(self, messages: ChatMessages) -> str:
        raise LLMUnavailable("LLM отключена: API-ключ не задан")

    async def structured(self, messages: ChatMessages, schema: type[T]) -> T:
        raise LLMUnavailable("LLM отключена: API-ключ не задан")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMUnavailable("LLM отключена: API-ключ не задан")


class OpenAICompatLLM:
    """Клиент текстовых ответов и эмбеддингов через OpenAI-совместимый API."""

    enabled = True

    def __init__(self, settings: Settings) -> None:
        self._model = settings.llm_model
        self._embeddings_model = settings.embeddings_model
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

        # Не включаем внутренние повторы SDK: ими управляет tenacity.
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or None,
            timeout=30.0,
            max_retries=0,
        )

    def _require_model(self, model: str | None) -> str:
        if not model:
            raise LLMUnavailable("Не задана модель LLM в настройках")
        return model

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _request_completion(
        self,
        messages: ChatMessages,
        model: str,
    ) -> str:
        """Выполнить один запрос; tenacity повторит только временные ошибки."""
        async with self._semaphore:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
            )

        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM вернула пустое текстовое сообщение")
        return content

    async def complete(self, messages: ChatMessages) -> str:
        """Получить обычный текстовый ответ."""
        model = self._require_model(self._model)

        try:
            return await self._request_completion(messages, model)
        except LLMUnavailable:
            raise
        except Exception as error:
            raise LLMUnavailable(
                "Не удалось получить ответ от LLM"
            ) from error

    async def structured(self, messages: ChatMessages, schema: type[T]) -> T:
        """Получить JSON и проверить его по Pydantic-схеме.

        При невалидном JSON или несовпадении со схемой делаем одну
        дополнительную попытку с просьбой исправить ответ.
        """
        model = self._require_model(self._model)
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)

        request_messages: ChatMessages = [
            {
                "role": "system",
                "content": (
                    "Верни только один корректный JSON-объект, без Markdown и пояснений. "
                    f"Он должен соответствовать этой JSON Schema: {schema_json}"
                ),
            },
            *[message.copy() for message in messages],
        ]

        for attempt in range(2):
            try:
                raw = await self._request_completion(request_messages, model)
            except LLMUnavailable:
                raise
            except Exception as error:
                raise LLMUnavailable(
                    "Не удалось получить структурированный ответ от LLM"
                ) from error

            try:
                return schema.model_validate_json(_strip_json_fence(raw))
            except ValidationError as error:
                if attempt == 1:
                    raise LLMUnavailable(
                        "Ответ LLM не прошёл проверку схемы после повторной попытки"
                    ) from error

                request_messages.extend(
                    [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "Предыдущий ответ не прошёл проверку. "
                                "Исправь JSON в соответствии со схемой и верни только JSON."
                            ),
                        },
                    ]
                )

        raise RuntimeError("Недостижимая ветка structured()")

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _request_embeddings(self, texts: list[str], model: str) -> list[list[float]]:
        async with self._semaphore:
            response = await self._client.embeddings.create(
                model=model,
                input=texts,
            )

        return [item.embedding for item in response.data]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Получить векторные представления текстов."""
        if not texts:
            return []

        model = self._require_model(self._embeddings_model)

        try:
            return await self._request_embeddings(texts, model)
        except LLMUnavailable:
            raise
        except Exception as error:
            raise LLMUnavailable(
                "Не удалось получить эмбеддинги от LLM"
            ) from error


def make_llm(settings: Settings) -> LLM:
    """Создать рабочий адаптер или заглушку без API-ключа."""
    if not settings.llm_api_key:
        return NullLLM()
    return OpenAICompatLLM(settings)