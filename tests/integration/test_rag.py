"""Интеграционные тесты индексации и полнотекстового поиска RAG."""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from trip_pilot.adapters.db.engine import create_engine, create_session_factory
from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination
from trip_pilot.config import get_settings
from trip_pilot.rag.index import build_index
from trip_pilot.rag.retriever import search

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION"),
    reason="Нужна PostgreSQL: docker compose --profile tests run --rm tests",
)


def on_db(scenario):
    """Запустить асинхронный сценарий с настоящей PostgreSQL."""

    async def wrapper():
        engine = create_engine(get_settings().database_url)
        try:
            sessions = create_session_factory(engine)
            return await scenario(sessions)
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


def make_document(
    knowledge_dir: Path,
    *,
    title: str,
    destination: str,
    body: str,
) -> None:
    """Создать тестовый Markdown-документ с корректным frontmatter."""
    content = f"""---
title: {title}
doc_type: guide
destination: {destination}
months: [5, 6, 7, 8, 9, 10]
tags: [sea, kids]
source: synthetic
---
{body}
"""
    (knowledge_dir / f"{destination}.md").write_text(
        content,
        encoding="utf-8",
    )


async def create_destination(session, slug: str) -> None:
    """Добавить уникальное направление, необходимое для индексации."""
    session.add(
        Destination(
            slug=slug,
            name=f"Тестовое направление {slug}",
            country="Тестовая страна",
            iata=None,
            lat=36.9,
            lon=30.7,
            timezone="Europe/Istanbul",
            is_synthetic=True,
        )
    )
    await session.flush()


async def count_documents(session, title: str) -> int:
    result = await session.scalar(
        select(func.count())
        .select_from(KbDocument)
        .where(KbDocument.title == title)
    )
    return result or 0


async def get_document(session, title: str) -> KbDocument:
    result = await session.scalar(
        select(KbDocument).where(KbDocument.title == title)
    )
    assert result is not None, f"Документ {title!r} не найден"
    return result


async def count_chunks(session, document_id) -> int:
    result = await session.scalar(
        select(func.count())
        .select_from(KbChunk)
        .where(KbChunk.document_id == document_id)
    )
    return result or 0


def test_build_index_is_idempotent_and_updates_changed_document(tmp_path):
    """Повторная индексация не дублирует документы, изменения обновляют фрагменты."""

    async def scenario(sessions):
        slug = f"rag-test-{uuid.uuid4().hex[:12]}"
        title = f"Тестовый путеводитель {slug}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=title,
                    destination=slug,
                    body=(
                        "## С детьми\n\n"
                        "Песчаные пляжи и семейные прогулки.\n\n"
                        "## Минусы и риски\n\n"
                        "Летом бывает жарко."
                    ),
                )

                await build_index(session, tmp_path)
                await session.flush()

                document = await get_document(session, title)
                initial_chunks = await count_chunks(session, document.id)

                assert initial_chunks >= 2
                assert await count_documents(session, title) == 1

                # Эмбеддинги в MVP не рассчитываются.
                embeddings = await session.scalars(
                    select(KbChunk.embedding).where(
                        KbChunk.document_id == document.id
                    )
                )
                assert all(embedding is None for embedding in embeddings.all())

                # Повторный запуск с неизменённым документом.
                await build_index(session, tmp_path)
                await session.flush()

                assert await count_documents(session, title) == 1
                assert await count_chunks(session, document.id) == initial_chunks

                # Меняем содержимое существующего документа.
                make_document(
                    tmp_path,
                    title=title,
                    destination=slug,
                    body=(
                        "## С детьми\n\n"
                        "Обновлённый текст о семейном отдыхе и детских площадках.\n\n"
                        "## Минусы и риски\n\n"
                        "Летом бывает жарко."
                    ),
                )

                await build_index(session, tmp_path)
                await session.flush()

                updated_document = await get_document(session, title)
                assert await count_documents(session, title) == 1

                updated_chunks = (
                    await session.scalars(
                        select(KbChunk).where(
                            KbChunk.document_id == updated_document.id
                        )
                    )
                ).all()

                assert updated_chunks
                assert any(
                    "детских площадках" in chunk.content
                    for chunk in updated_chunks
                )
            finally:
                await session.rollback()

    on_db(scenario)


def test_search_finds_children_section_and_filters_destination(tmp_path):
    """Полнотекстовый поиск на русском находит раздел нужного направления."""

    async def scenario(sessions):
        slug = f"rag-test-{uuid.uuid4().hex[:12]}"
        title = f"Путеводитель для поиска {slug}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=title,
                    destination=slug,
                    body=(
                        "## С детьми\n\n"
                        "Песчаные пляжи с пологим входом в море подходят "
                        "для семейного отдыха с детьми."
                    ),
                )

                await build_index(session, tmp_path)
                await session.flush()

                hits = await search(
                    session,
                    "с детьми",
                    destination=slug,
                    limit=5,
                )

                assert hits, "Поиск не вернул ни одного фрагмента"
                assert any(
                    "С детьми" in (hit.chunk.heading_path or "")
                    for hit in hits
                )
                assert any(
                    "дет" in hit.chunk.content.lower()
                    for hit in hits
                )

                # Поиск по несуществующему направлению не должен
                # возвращать документ из другого направления.
                other_hits = await search(
                    session,
                    "с детьми",
                    destination=f"missing-{slug}",
                    limit=5,
                )
                assert other_hits == []

                # Пустой запрос должен обрабатываться без исключения.
                empty_hits = await search(session, "   ", destination=slug)
                assert empty_hits == []
            finally:
                await session.rollback()

    on_db(scenario)
