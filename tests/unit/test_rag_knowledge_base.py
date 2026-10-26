"""Тесты адаптера PostgreSQL для порта KnowledgeBase."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.rag.retriever import PostgresKnowledgeBase, RetrievedChunk


def test_knowledge_base_maps_chunks_to_domain_hits(monkeypatch):
    """Адаптер преобразует результаты поиска в KnowledgeHit."""
    chunk = MagicMock()
    chunk.content = "Пляжи с пологим входом подходят для детей."
    chunk.heading_path = "Анталья › С детьми"

    retrieved = RetrievedChunk(
        chunk=chunk,
        document_title="Анталья",
        destination="antalya",
        score=0.75,
        source="synthetic",
    )

    session = MagicMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    search_mock = AsyncMock(return_value=[retrieved])
    monkeypatch.setattr("trip_pilot.rag.retriever.search", search_mock)

    knowledge_base = PostgresKnowledgeBase(session_factory)

    result = asyncio.run(
        knowledge_base.search(
            "с детьми",
            destination="antalya",
            doc_type="guide",
            limit=3,
        )
    )

    assert len(result) == 1
    assert isinstance(result[0], KnowledgeHit)
    assert result[0].text == chunk.content
    assert result[0].title == "Анталья"
    assert result[0].heading_path == "Анталья › С детьми"
    assert result[0].source == "synthetic"
    assert result[0].score == 0.75

    search_mock.assert_awaited_once_with(
        session,
        "с детьми",
        destination="antalya",
        doc_type="guide",
        limit=3,
    )


def test_knowledge_base_returns_empty_for_blank_query():
    """Пустой запрос не должен открывать сессию БД."""
    session_factory = MagicMock()
    knowledge_base = PostgresKnowledgeBase(session_factory)

    result = asyncio.run(knowledge_base.search("   "))

    assert result == []
    session_factory.assert_not_called()


def test_knowledge_base_returns_empty_for_non_positive_limit():
    """Неположительный лимит не должен открывать сессию БД."""
    session_factory = MagicMock()
    knowledge_base = PostgresKnowledgeBase(session_factory)

    result = asyncio.run(
        knowledge_base.search("с детьми", limit=0)
    )

    assert result == []
    session_factory.assert_not_called()
