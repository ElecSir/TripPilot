
"""Интеграционный тест гибридного RAG-поиска на PostgreSQL/pgvector."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from trip_pilot.adapters.db.engine import (
    create_engine,
    create_session_factory,
)
from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination
from trip_pilot.config import get_settings
from trip_pilot.rag.retriever import search

pytestmark = pytest.mark.skipif(
    not os.getenv("INTEGRATION"),
    reason="Запускается через docker compose --profile tests",
)


def test_hybrid_search_uses_real_pgvector():
    async def scenario():
        engine = create_engine(get_settings().database_url)

        try:
            sessions = create_session_factory(engine)

            async with sessions() as session:
                async with session.begin():
                    destination_result = await session.execute(
                        select(Destination).where(
                            Destination.slug == "antalya"
                        )
                    )
                    destination = destination_result.scalar_one()

                    unique_id = uuid.uuid4()
                    document = KbDocument(
                        id=unique_id,
                        source="synthetic",
                        source_url=f"integration-{unique_id}.md",
                        title="Integration RAG test",
                        doc_type="destination",
                        destination_id=destination.id,
                        is_synthetic=True,
                        content_hash=str(unique_id),
                    )
                    session.add(document)
                    await session.flush()

                    query_vector = [0.0] * 1024
                    query_vector[0] = 1.0

                    unrelated_vector = [0.0] * 1024
                    unrelated_vector[1] = 1.0

                    text_chunk = KbChunk(
                        document_id=document.id,
                        heading_path="Почему ехать",
                        content=(
                            "Семейный отдых дети пляж "
                            "в Анталье у моря"
                        ),
                        meta={},
                        embedding=unrelated_vector,
                        embedding_model="integration-test",
                    )
                    vector_chunk = KbChunk(
                        document_id=document.id,
                        heading_path="Минусы и риски",
                        content="Горные прогулки в лесу",
                        meta={},
                        embedding=query_vector,
                        embedding_model="integration-test",
                    )
                    session.add_all([text_chunk, vector_chunk])
                    await session.flush()

                    text_chunk_id = text_chunk.id
                    vector_chunk_id = vector_chunk.id

                    llm = MagicMock()
                    llm.enabled = True
                    llm.embed = AsyncMock(
                        return_value=[query_vector]
                    )

                    with patch(
                        "trip_pilot.rag.retriever._get_llm",
                        return_value=llm,
                    ):
                        results = await search(
                            session,
                            "семейный отдых дети",
                            destination="antalya",
                            limit=5,
                        )

                    result_ids = [item.chunk.id for item in results]

                    # Полнотекстовый поиск находит текстовый фрагмент.
                    assert text_chunk_id in result_ids

                    # Векторный поиск находит семантически близкий фрагмент.
                    assert vector_chunk_id in result_ids

                    # Оба результата объединены без дубликатов.
                    assert len(result_ids) == len(set(result_ids))

                    llm.embed.assert_awaited_once_with(
                        ["семейный отдых дети"]
                    )

                    # Удаляем тестовые строки через rollback.
                    raise _RollbackIntegrationTest()

        except _RollbackIntegrationTest:
            pass
        finally:
            await engine.dispose()

    asyncio.run(scenario())


class _RollbackIntegrationTest(Exception):
    """Вспомогательное исключение для отката тестовой транзакции."""
