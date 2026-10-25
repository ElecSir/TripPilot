"""Полнотекстовый поиск и адаптер базы знаний RAG."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination
from trip_pilot.domain.knowledge import KnowledgeHit

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


async def search(
    session: AsyncSession,
    query: str,
    destination: str | None = None,
    doc_type: str | None = None,
    limit: int = 5,
) -> list[RetrievedChunk]:
    """Найти наиболее релевантные фрагменты по текстовому запросу."""
    if not query or not query.strip() or limit <= 0:
        return []

    ts_query = func.websearch_to_tsquery("russian", query.strip())

    statement = (
        select(
            KbChunk,
            KbDocument.title.label("document_title"),
            KbDocument.source.label("source"),
            Destination.slug.label("destination"),
            func.ts_rank_cd(KbChunk.tsv, ts_query).label("score"),
        )
        .join(KbDocument, KbChunk.document_id == KbDocument.id)
        .outerjoin(
            Destination,
            KbDocument.destination_id == Destination.id,
        )
        .where(KbChunk.tsv.op("@@")(ts_query))
    )

    if destination:
        statement = statement.where(Destination.slug == destination)

    if doc_type:
        statement = statement.where(KbDocument.doc_type == doc_type)

    statement = statement.order_by(
        func.ts_rank_cd(KbChunk.tsv, ts_query).desc()
    ).limit(limit)

    result = await session.execute(statement)

    return [
        RetrievedChunk(
            chunk=row[0],
            document_title=row.document_title,
            destination=row.destination,
            score=float(row.score),
            source=row.source,
        )
        for row in result.all()
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
