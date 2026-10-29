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
from trip_pilot.domain.request import Party, TripRequest
from trip_pilot.rag.index import build_index
from trip_pilot.rag.retriever import PostgresKnowledgeBase, search

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
    doc_type: str = "guide",
) -> None:
    """Создать тестовый Markdown-документ с корректным frontmatter."""
    content = f"""---
title: {title}
doc_type: {doc_type}
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


def test_build_index_renames_title_without_duplicate(tmp_path):
    """Изменение title обновляет документ, а не создаёт дубликат."""

    async def scenario(sessions):
        slug = f"rag-test-{uuid.uuid4().hex[:12]}"
        filename = f"{slug}.md"
        old_title = f"Старое название {slug}"
        new_title = f"Новое название {slug}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=old_title,
                    destination=slug,
                    doc_type="destination",
                    body=(
                        "## Почему ехать\n\n"
                        "Описание направления для тестирования."
                    ),
                )

                await build_index(session, tmp_path)
                await session.flush()

                original = await session.scalar(
                    select(KbDocument).where(
                        KbDocument.source_url == filename
                    )
                )
                assert original is not None
                original_id = original.id

                initial_chunks = await count_chunks(session, original_id)
                assert initial_chunks > 0

                # Меняем только заголовок, не имя файла.
                make_document(
                    tmp_path,
                    title=new_title,
                    destination=slug,
                    doc_type="destination",
                    body=(
                        "## Почему ехать\n\n"
                        "Описание направления для тестирования."
                    ),
                )

                await build_index(session, tmp_path)
                await session.flush()

                documents = (
                    await session.scalars(
                        select(KbDocument).where(
                            KbDocument.source_url == filename
                        )
                    )
                ).all()

                assert len(documents) == 1
                assert documents[0].id == original_id
                assert documents[0].title == new_title

                assert await count_documents(session, old_title) == 0
                assert await count_documents(session, new_title) == 1
                assert await count_chunks(session, original_id) == initial_chunks
            finally:
                await session.rollback()

    on_db(scenario)


def test_build_index_deletes_removed_document_and_chunks(tmp_path):
    """Удаление Markdown-файла удаляет документ и все его фрагменты."""

    async def scenario(sessions):
        slug = f"rag-test-{uuid.uuid4().hex[:12]}"
        filename = f"{slug}.md"
        title = f"Удаляемый документ {slug}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=title,
                    destination=slug,
                    doc_type="destination",
                    body=(
                        "## Почему ехать\n\n"
                        "Первый тестовый фрагмент.\n\n"
                        "## Минусы и риски\n\n"
                        "Второй тестовый фрагмент."
                    ),
                )

                await build_index(session, tmp_path)
                await session.flush()

                document = await session.scalar(
                    select(KbDocument).where(
                        KbDocument.source_url == filename
                    )
                )
                assert document is not None

                document_id = document.id
                assert await count_chunks(session, document_id) > 0

                # Удаляем исходный файл и повторно запускаем индексацию.
                (tmp_path / filename).unlink()

                await build_index(session, tmp_path)
                await session.flush()

                remaining_document = await session.scalar(
                    select(KbDocument).where(
                        KbDocument.source_url == filename
                    )
                )
                remaining_chunks = await count_chunks(session, document_id)

                assert remaining_document is None
                assert remaining_chunks == 0
            finally:
                await session.rollback()

    on_db(scenario)


def test_search_finds_animal_and_season_sections(tmp_path):
    """Запросы о собаке и сезоне находят тематические разделы."""

    async def scenario(sessions):
        slug = f"rag-test-{uuid.uuid4().hex[:12]}"
        title = f"Путеводитель для тематического поиска {slug}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=title,
                    destination=slug,
                    doc_type="destination",
                    body=(
                        "## С животными\n\n"
                        "Путешественники могут планировать отдых "
                        "вместе с домашними питомцами.\n\n"
                        "## Когда лучше\n\n"
                        "Выбирайте сезон поездки с учётом климата "
                        "и погодных условий."
                    ),
                )

                await build_index(session, tmp_path)
                await session.flush()

                animal_hits = await search(
                    session,
                    "можно ли с собакой",
                    destination=slug,
                    limit=5,
                )

                assert animal_hits, "Поиск по собаке ничего не нашёл"
                assert any(
                    "С животными" in (hit.chunk.heading_path or "")
                    for hit in animal_hits
                )

                season_hits = await search(
                    session,
                    "когда лучше ехать",
                    destination=slug,
                    limit=5,
                )

                assert season_hits, "Поиск по сезону ничего не нашёл"
                assert any(
                    "Когда лучше" in (hit.chunk.heading_path or "")
                    for hit in season_hits
                )
            finally:
                await session.rollback()

    on_db(scenario)


def test_context_returns_relevant_sections_in_priority_order(tmp_path):
    """Контекст для поездки с детьми в ноябре содержит нужные разделы."""

    async def scenario(sessions):
        slug = f"rag-context-{uuid.uuid4().hex[:12]}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=f"Путеводитель {slug}",
                    destination=slug,
                    body=(
                        "## Почему ехать\n\nОписание направления.\n\n"
                        "## Когда лучше\n\nОсобенности погоды.\n\n"
                        "## С детьми\n\nСоветы для семей.\n\n"
                        "## С животными\n\nСоветы путешественникам с питомцами.\n\n"
                        "## Минусы и риски\n\nВозможные неудобства."
                    ),
                )

                await build_index(session, tmp_path)
                await session.commit()

                knowledge_base = PostgresKnowledgeBase(sessions)
                request = TripRequest(
                    month=11,
                    party=Party(children_ages=[7]),
                )

                hits = await knowledge_base.context(request, slug)

                headings = [
                    hit.heading_path.split(" › ")[-1]
                    for hit in hits
                ]

                assert headings == [
                    "Почему ехать",
                    "С детьми",
                    "Когда лучше",
                    "Минусы и риски",
                ]
            finally:
                await session.rollback()

    on_db(scenario)


def test_context_returns_empty_for_unknown_destination():
    """Для неизвестного направления контекст пустой, а не ошибка."""

    async def scenario(sessions):
        knowledge_base = PostgresKnowledgeBase(sessions)

        result = await knowledge_base.context(
            TripRequest(),
            "missing-destination-for-context-test",
        )

        assert result == []

    on_db(scenario)


def test_context_includes_general_animal_rules(tmp_path):
    """При поездке с питомцем контекст содержит общие правила перевозки животных."""

    async def scenario(sessions):
        slug = f"rag-animals-{uuid.uuid4().hex[:12]}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=f"Путеводитель {slug}",
                    destination=slug,
                    body=(
                        "## Почему ехать\n\n"
                        "Описание направления.\n\n"
                        "## С животными\n\n"
                        "Отдых с питомцами."
                    ),
                )

                rules_dir = tmp_path / "rules"
                rules_dir.mkdir()

                (rules_dir / "animals.md").write_text(
                    "---\n"
                    "title: Правила перевозки животных\n"
                    "doc_type: rules\n"
                    "destination: null\n"
                    "months: []\n"
                    "tags: [animals, transport]\n"
                    "source: synthetic\n"
                    "---\n"
                    "## В самолёте\n\n"
                    "Проверьте документы и требования к переноске.\n\n"
                    "## В поезде\n\n"
                    "Заранее уточните условия перевозки животного.\n",
                    encoding="utf-8",
                )

                await build_index(session, tmp_path)
                await session.commit()

                request = TripRequest(
                    party=Party(pets=["dog"]),
                )
                knowledge_base = PostgresKnowledgeBase(sessions)

                hits = await knowledge_base.context(request, slug)

                assert any(
                    hit.title == "Правила перевозки животных"
                    for hit in hits
                )
            finally:
                await session.rollback()

    on_db(scenario)


def test_context_includes_general_child_rules(tmp_path):
    """При поездке с детьми контекст содержит общие правила для детей."""

    async def scenario(sessions):
        slug = f"rag-children-{uuid.uuid4().hex[:12]}"

        async with sessions() as session:
            try:
                await create_destination(session, slug)

                make_document(
                    tmp_path,
                    title=f"Путеводитель {slug}",
                    destination=slug,
                    body=(
                        "## Почему ехать\n\n"
                        "Описание направления.\n\n"
                        "## С детьми\n\n"
                        "Советы для семей."
                    ),
                )

                rules_dir = tmp_path / "rules"
                rules_dir.mkdir()

                (rules_dir / "children.md").write_text(
                    "---\n"
                    "title: Документы и билеты для детей\n"
                    "doc_type: rules\n"
                    "destination: null\n"
                    "months: []\n"
                    "tags: [children, documents, tickets]\n"
                    "source: synthetic\n"
                    "---\n"
                    "## Документы ребёнка\n\n"
                    "Перед поездкой проверьте документы ребёнка.\n\n"
                    "## Билеты и сопровождение\n\n"
                    "Уточните правила оформления детского билета.\n",
                    encoding="utf-8",
                )

                await build_index(session, tmp_path)
                await session.commit()

                request = TripRequest(
                    party=Party(children_ages=[7]),
                )
                knowledge_base = PostgresKnowledgeBase(sessions)

                hits = await knowledge_base.context(request, slug)

                assert any(
                    hit.title == "Документы и билеты для детей"
                    for hit in hits
                )
            finally:
                await session.rollback()

    on_db(scenario)