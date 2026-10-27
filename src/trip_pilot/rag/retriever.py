"""Полнотекстовый поиск и адаптер базы знаний RAG."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination
from trip_pilot.domain.knowledge import KnowledgeHit
from trip_pilot.domain.request import TripRequest

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

    return [
        RetrievedChunk(
            chunk=row[0],
            document_title=row.document_title,
            destination=row.destination,
            score=float(row.score),
            source=row.source,
        )
        for row in rows
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
        """Разделы под запрос для объяснений. Заглушка лида: пока пусто.

        rag заменяет тело (задача 3 в tasks/rag.md).
        """
        return []
