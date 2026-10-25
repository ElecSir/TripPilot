"""Полнотекстовый поиск по базе знаний RAG."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination


@dataclass(frozen=True)
class RetrievedChunk:
    """Результат поиска по базе знаний."""

    chunk: KbChunk
    document_title: str
    destination: str | None
    score: float


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
        )
        for row in result.all()
    ]
