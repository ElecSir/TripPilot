
"""Юнит-тесты LLM-адаптера без сетевых запросов."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError
from pydantic import BaseModel

from trip_pilot.adapters.llm.openai_compat import (
    NullLLM,
    OpenAICompatLLM,
    make_llm,
)
from trip_pilot.config import Settings
from trip_pilot.ports import LLMUnavailable


def run(coro):
    return asyncio.run(coro)


def completion_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def make_adapter(monkeypatch):
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock()),
        ),
        embeddings=SimpleNamespace(
            create=AsyncMock(),
        ),
    )

    monkeypatch.setattr(
        "trip_pilot.adapters.llm.openai_compat.AsyncOpenAI",
        lambda **kwargs: client,
    )

    settings = Settings(
        llm_api_key="test-key-not-real",
        llm_model="test-model",
        embeddings_model="test-embeddings",
        llm_max_concurrency=2,
    )
    return OpenAICompatLLM(settings), client


class Greeting(BaseModel):
    text: str


def test_make_llm_without_key_returns_null_llm():
    llm = make_llm(Settings(llm_api_key=None))

    assert isinstance(llm, NullLLM)
    assert llm.enabled is False

    with pytest.raises(LLMUnavailable):
        run(llm.complete([{"role": "user", "content": "Привет"}]))

    with pytest.raises(LLMUnavailable):
        run(llm.structured([], Greeting))

    with pytest.raises(LLMUnavailable):
        run(llm.embed(["Привет"]))


def test_complete_returns_model_text(monkeypatch):
    llm, client = make_adapter(monkeypatch)
    client.chat.completions.create.return_value = completion_response("Привет!")

    result = run(llm.complete([{"role": "user", "content": "Привет"}]))

    assert result == "Привет!"
    client.chat.completions.create.assert_awaited_once()


def test_structured_validates_pydantic_schema(monkeypatch):
    llm, client = make_adapter(monkeypatch)
    client.chat.completions.create.return_value = completion_response(
        '{"text": "Поехали в Сочи"}'
    )

    result = run(llm.structured([], Greeting))

    assert result == Greeting(text="Поехали в Сочи")


def test_structured_retries_once_after_invalid_json(monkeypatch):
    llm, client = make_adapter(monkeypatch)
    client.chat.completions.create.side_effect = [
        completion_response('{"wrong": 123}'),
        completion_response('{"text": "Привет"}'),
    ]

    result = run(llm.structured([], Greeting))

    assert result == Greeting(text="Привет")
    assert client.chat.completions.create.await_count == 2


def test_structured_raises_llm_unavailable_after_second_invalid_response(
    monkeypatch,
):
    llm, client = make_adapter(monkeypatch)
    client.chat.completions.create.return_value = completion_response(
        '{"wrong": 123}'
    )

    with pytest.raises(LLMUnavailable):
        run(llm.structured([], Greeting))

    assert client.chat.completions.create.await_count == 2


def test_complete_retries_network_error(monkeypatch):
    llm, client = make_adapter(monkeypatch)
    request = httpx.Request("POST", "https://example.com")
    client.chat.completions.create.side_effect = [
        APIConnectionError(request=request),
        completion_response("Успех"),
    ]

    result = run(llm.complete([{"role": "user", "content": "Привет"}]))

    assert result == "Успех"
    assert client.chat.completions.create.await_count == 2


def test_embed_returns_vectors(monkeypatch):
    llm, client = make_adapter(monkeypatch)
    client.embeddings.create.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(embedding=[0.1, 0.2]),
            SimpleNamespace(embedding=[0.3, 0.4]),
        ]
    )

    result = run(llm.embed(["первый текст", "второй текст"]))

    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_empty_input_does_not_call_api(monkeypatch):
    llm, client = make_adapter(monkeypatch)

    assert run(llm.embed([])) == []
    client.embeddings.create.assert_not_awaited()


@pytest.mark.parametrize("status_code", [401, 403])
def test_complete_raises_llm_unavailable_on_auth_error(
    monkeypatch,
    status_code,
):
    llm, client = make_adapter(monkeypatch)
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://example.com"),
    )
    from openai import AuthenticationError, PermissionDeniedError

    if status_code == 401:
        error = AuthenticationError(
            "Недействительный ключ",
            response=response,
            body=None,
        )
    else:
        error = PermissionDeniedError(
            "Доступ запрещён",
            response=response,
            body=None,
        )

    client.chat.completions.create.side_effect = error

    with pytest.raises(LLMUnavailable):
        run(llm.complete([{"role": "user", "content": "Привет"}]))


def test_complete_raises_llm_unavailable_after_network_retries(
    monkeypatch,
):
    llm, client = make_adapter(monkeypatch)
    request = httpx.Request("POST", "https://example.com")
    client.chat.completions.create.side_effect = APIConnectionError(
        request=request
    )

    with pytest.raises(LLMUnavailable):
        run(llm.complete([{"role": "user", "content": "Привет"}]))


def test_structured_accepts_json_markdown_fence(monkeypatch):
    llm, client = make_adapter(monkeypatch)
    client.chat.completions.create.return_value = completion_response(
        '```json\n{"text": "Поехали в Сочи"}\n```'
    )

    result = run(llm.structured([], Greeting))

    assert result == Greeting(text="Поехали в Сочи")
    client.chat.completions.create.assert_awaited_once()


def test_complete_raises_llm_unavailable_after_rate_limit_retries(
    monkeypatch,
):
    llm, client = make_adapter(monkeypatch)

    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(429, request=request)

    from openai import RateLimitError

    error = RateLimitError(
        "Превышен лимит запросов",
        response=response,
        body=None,
    )
    client.chat.completions.create.side_effect = error

    with pytest.raises(LLMUnavailable):
        run(llm.complete([{"role": "user", "content": "Привет"}]))

    assert client.chat.completions.create.await_count == 3
    