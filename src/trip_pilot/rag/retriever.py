"""Полнотекстовый поиск и адаптер базы знаний RAG."""

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination
from trip_pilot.adapters.llm.openai_compat import make_llm
from trip_pilot.config import get_settings
from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.request import TripRequest
from trip_pilot.ports import LLMUnavailable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker


@dataclass(frozen=True)
class RetrievedChunk:
    """Результат внутреннего поиска по базе знаний."""

    chunk: KbChunk
    document_title: str
    destination: str | None
    score: float
    source: str


_SECTION_SYNONYMS = {
    "animals": {
        "prefixes": ("собак", "кош", "питом", "животн"),
        "heading": "%С животными%",
        "terms": ("животными", "животное", "питомец"),
    },
    "season": {
        "prefixes": ("сезон", "погод", "климат", "когда", "ехать"),
        "heading": "%Когда лучше%",
        "terms": ("сезон", "погода", "климат"),
    },
    "kids": {
        "prefixes": ("ребен", "ребён", "дет", "сем"),
        "heading": "%С детьми%",
        "terms": ("ребёнок", "дети", "семья"),
    },
}

@lru_cache(maxsize=1)
def _get_llm():
    """Создать LLM-клиент один раз и повторно использовать его."""
    return make_llm(get_settings())

async def search(
    session: AsyncSession,
    query: str,
    destination: str | None = None,
    doc_type: str | None = None,
    limit: int = 5,
) -> list[RetrievedChunk]:
    """Найти релевантные фрагменты, включая поиск по отдельным словам."""
    if not query or not query.strip() or limit <= 0:
        return []

    tokens = list(dict.fromkeys(re.findall(r"[a-zа-яё0-9]+", query.casefold())))
    if not tokens:
        return []

    base_statement = (
        select(
            KbChunk,
            KbDocument.title.label("document_title"),
            KbDocument.source.label("source"),
            Destination.slug.label("destination"),
        )
        .join(KbDocument, KbChunk.document_id == KbDocument.id)
        .outerjoin(
            Destination,
            KbDocument.destination_id == Destination.id,
        )
    )

    if destination:
        base_statement = base_statement.where(Destination.slug == destination)

    if doc_type:
        base_statement = base_statement.where(KbDocument.doc_type == doc_type)

    # Сначала пробуем строгий полнотекстовый поиск.
    strict_query = func.websearch_to_tsquery("russian", query.strip())
    strict_statement = (
        base_statement
        .add_columns(
            func.ts_rank_cd(KbChunk.tsv, strict_query).label("score")
        )
        .where(KbChunk.tsv.op("@@")(strict_query))
        .order_by(func.ts_rank_cd(KbChunk.tsv, strict_query).desc())
        .limit(limit)
    )

    result = await session.execute(strict_statement)
    rows = result.all()

    # Пытаемся получить embedding поискового запроса.
    # Если это не получится, останется полнотекстовый поиск.
    query_vector = None

    try:
        llm = _get_llm()

        if llm.enabled:
            embeddings = await llm.embed([query.strip()])

            if embeddings and len(embeddings[0]) == 1024:
                query_vector = embeddings[0]

    except LLMUnavailable:
        # API недоступен — продолжаем работать без векторного поиска.
        query_vector = None

    # Если строгий поиск ничего не нашёл, ищем по любому слову
    # и добавляем синонимы тематических разделов.
    if not rows:
        fallback_terms = list(tokens)
        heading_conditions = []

        for synonym in _SECTION_SYNONYMS.values():
            if any(
                token.startswith(synonym["prefixes"])
                for token in tokens
            ):
                heading_conditions.append(
                    KbChunk.heading_path.ilike(synonym["heading"])
                )
                fallback_terms.extend(synonym["terms"])

        fallback_terms = list(dict.fromkeys(fallback_terms))
        fallback_query = func.websearch_to_tsquery(
            "russian",
            " OR ".join(fallback_terms),
        )

        word_conditions = [
            KbChunk.tsv.op("@@")(
                func.plainto_tsquery("russian", token)
            )
            for token in tokens
        ]

        conditions = [*word_conditions, *heading_conditions]

        fallback_statement = (
            base_statement
            .add_columns(
                func.ts_rank_cd(KbChunk.tsv, fallback_query).label("score")
            )
            .where(or_(*conditions))
            .order_by(
                func.ts_rank_cd(KbChunk.tsv, fallback_query).desc()
            )
            .limit(limit)
        )

        result = await session.execute(fallback_statement)
        rows = result.all()

    
    # Преобразуем результаты полнотекстового поиска.
    text_hits = [
        RetrievedChunk(
            chunk=row[0],
            document_title=row.document_title,
            destination=row.destination,
            score=float(row.score),
            source=row.source,
        )
        for row in rows
    ]

    # Если embedding получить не удалось, используем только полнотекстовый поиск.
    if query_vector is None:
        return text_hits

    # Векторный поиск по PostgreSQL с pgvector.
    vector_statement = (
        base_statement
        .add_columns(
            KbChunk.embedding.cosine_distance(query_vector).label("distance")
        )
        .where(KbChunk.embedding.is_not(None))
        .order_by(KbChunk.embedding.cosine_distance(query_vector))
        .limit(limit)
    )

    vector_result = await session.execute(vector_statement)
    vector_rows = vector_result.all()

    vector_hits = [
        RetrievedChunk(
            chunk=row[0],
            document_title=row.document_title,
            destination=row.destination,
            score=float(row.distance),
            source=row.source,
        )
        for row in vector_rows
    ]

    # Объединяем результаты через Reciprocal Rank Fusion (RRF).
    # Чем выше позиция фрагмента в выдаче, тем больше его вклад.
    rrf_k = 60
    fused: dict[int, tuple[RetrievedChunk, float]] = {}

    for ranked_hits in (text_hits, vector_hits):
        for rank, hit in enumerate(ranked_hits, start=1):
            chunk_id = hit.chunk.id
            contribution = 1.0 / (rrf_k + rank)

            if chunk_id in fused:
                previous_hit, previous_score = fused[chunk_id]
                fused[chunk_id] = (
                    previous_hit,
                    previous_score + contribution,
                )
            else:
                fused[chunk_id] = (hit, contribution)

    # Сортируем по итоговому RRF-score и возвращаем не больше limit фрагментов.
    ranked_results = sorted(
        fused.values(),
        key=lambda item: item[1],
        reverse=True,
    )

    return [
        replace(hit, score=rrf_score)
        for hit, rrf_score in ranked_results[:limit]
    ]


class PostgresKnowledgeBase:
    """Реализация порта KnowledgeBase через PostgreSQL."""

    def __init__(
        self,
        session_factory: "async_sessionmaker[AsyncSession]",
    ) -> None:
        self._session_factory = session_factory

    async def search(
        self,
        query: str,
        *,
        destination: str | None = None,
        doc_type: str | None = None,
        limit: int = 5,
    ) -> list[KnowledgeHit]:
        """Найти фрагменты и вернуть их в формате доменного контракта."""
        if not query or not query.strip() or limit <= 0:
            return []

        async with self._session_factory() as session:
            chunks = await search(
                session,
                query,
                destination=destination,
                doc_type=doc_type,
                limit=limit,
            )

        return [
            KnowledgeHit(
                text=item.chunk.content,
                title=item.document_title,
                heading_path=item.chunk.heading_path,
                source=item.source,
                score=item.score,
            )
            for item in chunks
        ]

    async def context(
        self, request: TripRequest, destination: str, *, limit: int = 4
    ) -> list[KnowledgeHit]:
        """Подобрать разделы базы знаний для объяснения поездки."""
        if not destination or limit <= 0:
            return []

        # Сначала проверяем, что направление существует.
        async with self._session_factory() as session:
            destination_id = await session.scalar(
                select(Destination.id).where(Destination.slug == destination)
            )

            if destination_id is None:
                return []

            # Разделы упорядочены по важности для объяснения.
            headings = ["Почему ехать"]

            if request.party.children_ages:
                headings.append("С детьми")

            if request.party.pets:
                headings.append("С животными")

            if request.month is not None:
                headings.append("Когда лучше")

            headings.append("Минусы и риски")

            # Ищем именно по заголовку, не по полнотекстовому индексу.
            conditions = [
                KbChunk.heading_path.ilike(f"% › {heading}")
                for heading in headings
            ]

            statement = (
                select(
                    KbChunk,
                    KbDocument.title.label("document_title"),
                    KbDocument.source.label("source"),
                )
                .join(KbDocument, KbChunk.document_id == KbDocument.id)
                .where(
                    KbDocument.destination_id == destination_id,
                    KbDocument.doc_type == "guide",
                    or_(*conditions),
                )
            )

            result = await session.execute(statement)
            rows = result.all()

        # Сохраняем приоритет заголовков, независимо от порядка в БД.
        priority = {
            heading: index
            for index, heading in enumerate(headings)
        }

        hits = [
            KnowledgeHit(
                text=row[0].content,
                title=row.document_title,
                heading_path=row[0].heading_path,
                source=row.source,
                score=float(
                    priority.get(
                        (row[0].heading_path or "").split(" › ")[-1],
                        len(priority),
                    )
                ),
            )
            for row in rows
        ]

        hits.sort(key=lambda hit: hit.score)
        return hits[:limit]
