"""Тесты индексации базы знаний RAG."""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.ports import LLMUnavailable
from trip_pilot.rag.index import build_index, embed_index


def make_markdown() -> str:
    """Создать тестовый Markdown-документ."""
    return """---
title: Анталья
doc_type: destination
destination: antalya
months:
  - 5
  - 6
tags:
  - море
  - семья
source: synthetic
---

Описание направления.

## Почему ехать

Подходит для пляжного отдыха.

## С детьми

Есть варианты семейного отдыха.
"""


def make_result(value):
    """Создать результат запроса с scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def make_session(*results):
    session = MagicMock()

    empty_result = make_result(None)
    empty_result.scalars.return_value.all.return_value = []

    session.execute = AsyncMock(
        side_effect=[empty_result, *results]
    )
    session.flush = AsyncMock()
    session.add = MagicMock()

    return session


def test_build_index_adds_new_document_and_chunks(tmp_path):
    """Новый документ и его фрагменты добавляются в БД."""
    (tmp_path / "antalya.md").write_text(
        make_markdown(),
        encoding="utf-8",
    )

    destination = MagicMock()
    destination.id = 1

    session = make_session(
        make_result(destination),
        make_result(None),
    )

    asyncio.run(build_index(session, tmp_path))

    added_objects = [
        call.args[0]
        for call in session.add.call_args_list
    ]

    documents = [
        obj for obj in added_objects
        if isinstance(obj, KbDocument)
    ]
    chunks = [
        obj for obj in added_objects
        if isinstance(obj, KbChunk)
    ]

    assert len(documents) == 1
    assert documents[0].title == "Анталья"
    assert documents[0].doc_type == "destination"
    assert documents[0].destination_id == 1
    assert documents[0].is_synthetic is True
    assert len(documents[0].content_hash) == 64

    assert len(chunks) == 3
    assert any("Почему ехать" in chunk.content for chunk in chunks)
    assert any("С детьми" in chunk.content for chunk in chunks)

    session.flush.assert_awaited_once()


def test_build_index_skips_unchanged_document(tmp_path):
    """Неизменившийся документ повторно не добавляется."""
    content = make_markdown()
    (tmp_path / "antalya.md").write_text(content, encoding="utf-8")

    destination = MagicMock()
    destination.id = 1

    document = MagicMock()
    document.content_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    session = make_session(
        make_result(destination),
        make_result(document),
    )

    asyncio.run(build_index(session, tmp_path))

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def test_build_index_updates_existing_document(tmp_path):
    """Изменённый документ обновляется, старые фрагменты удаляются."""
    content = make_markdown().replace(
        "Подходит для пляжного отдыха.",
        "Подходит для семейного пляжного отдыха.",
    )
    (tmp_path / "antalya.md").write_text(content, encoding="utf-8")

    destination = MagicMock()
    destination.id = 1

    document = MagicMock()
    document.id = "test-document-id"
    document.content_hash = "old-hash"

    session = make_session(
        make_result(destination),
        make_result(document),
        MagicMock(),
    )

    asyncio.run(build_index(session, tmp_path))

    session.execute.assert_awaited()
    assert document.content_hash == hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()
    assert document.destination_id == 1
    assert session.add.called
    session.flush.assert_not_awaited()


def test_build_index_raises_if_destination_missing(tmp_path):
    """Индексация завершается ошибкой, если направления нет в БД."""
    (tmp_path / "antalya.md").write_text(
        make_markdown(),
        encoding="utf-8",
    )

    session = make_session(make_result(None))

    with pytest.raises(ValueError, match="antalya"):
        asyncio.run(build_index(session, tmp_path))

    session.add.assert_not_called()


def test_build_index_handles_missing_directory(tmp_path):
    """Отсутствующая папка не приводит к ошибке."""
    missing_dir = tmp_path / "missing"
    session = make_session()

    asyncio.run(build_index(session, missing_dir))

    session.execute.assert_not_awaited()
    session.add.assert_not_called()

def test_build_index_updates_title_without_creating_duplicate(tmp_path):
    """Переименование заголовка обновляет существующий документ."""
    content = make_markdown().replace("title: Анталья", "title: Анталья — море")
    (tmp_path / "antalya.md").write_text(content, encoding="utf-8")

    destination = MagicMock()
    destination.id = 1

    document = MagicMock()
    document.id = "test-document-id"
    document.title = "Анталья"
    document.content_hash = "old-hash"
    document.source_url = "antalya.md"

    session = make_session(
        make_result(destination),
        make_result(document),
        MagicMock(),
    )

    asyncio.run(build_index(session, tmp_path))

    assert document.title == "Анталья — море"
    assert document.source_url == "antalya.md"
    session.add.assert_called()

def test_build_index_deletes_documents_for_removed_files(tmp_path):
    """Документ и его фрагменты удаляются, если исходного файла больше нет."""
    document = MagicMock()
    document.id = "removed-document-id"
    document.source_url = "old_destination.md"

    cleanup_result = MagicMock()
    cleanup_result.scalars.return_value.all.return_value = [document]

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            cleanup_result,
            MagicMock(),
            MagicMock(),
        ]
    )
    session.flush = AsyncMock()
    session.add = MagicMock()

    asyncio.run(build_index(session, tmp_path))

    assert session.execute.await_count == 3


class FakeEmbeddingLLM:
    enabled = True

    def __init__(self, vectors=None, error=None):
        self.vectors = vectors
        self.error = error
        self.calls = []

    async def embed(self, texts):
        self.calls.append(texts)
        if self.error:
            raise self.error
        return self.vectors


def make_embedding_session(chunks):
    result = MagicMock()
    result.scalars.return_value.all.return_value = chunks

    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


def test_embed_index_saves_vectors_and_model(monkeypatch):
    """Эмбеддинги и название модели сохраняются во фрагментах."""
    monkeypatch.setenv("EMBEDDINGS_MODEL", "test-embedding-model")

    chunk = KbChunk(
        document_id="test-document",
        content="Отдых у моря",
        embedding=None,
        embedding_model=None,
    )
    session = make_embedding_session([chunk])
    llm = FakeEmbeddingLLM(vectors=[[0.1] * 1024])

    asyncio.run(embed_index(session, llm))

    assert chunk.embedding == [0.1] * 1024
    assert chunk.embedding_model == "test-embedding-model"
    assert len(llm.calls) == 1
    session.flush.assert_awaited_once()


def test_embed_index_skips_when_llm_disabled():
    """Без LLM индексация пропускается."""
    session = make_embedding_session([])
    llm = FakeEmbeddingLLM()
    llm.enabled = False

    asyncio.run(embed_index(session, llm))

    session.execute.assert_not_awaited()
    assert llm.calls == []


def test_embed_index_handles_llm_unavailable(monkeypatch):
    """Ошибка LLM не приводит к падению bootstrap."""
    monkeypatch.setenv("EMBEDDINGS_MODEL", "test-embedding-model")

    chunk = KbChunk(
        document_id="test-document",
        content="Отдых у моря",
        embedding=None,
        embedding_model=None,
    )
    session = make_embedding_session([chunk])
    llm = FakeEmbeddingLLM(error=LLMUnavailable("API недоступен"))

    asyncio.run(embed_index(session, llm))

    assert chunk.embedding is None
    session.flush.assert_not_awaited()


def test_embed_index_skips_wrong_dimensions(monkeypatch, caplog):
    """Вектор неверной размерности не сохраняется."""
    monkeypatch.setenv("EMBEDDINGS_MODEL", "test-embedding-model")

    chunk = KbChunk(
        document_id="test-document",
        content="Отдых у моря",
        embedding=None,
        embedding_model=None,
    )
    session = make_embedding_session([chunk])
    llm = FakeEmbeddingLLM(vectors=[[0.1] * 768])

    asyncio.run(embed_index(session, llm))

    assert chunk.embedding is None
    assert chunk.embedding_model is None
    assert "размерность" in caplog.text.lower()
    session.flush.assert_not_awaited()