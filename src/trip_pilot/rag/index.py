"""Индексация Markdown-базы знаний в PostgreSQL."""

import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.knowledge import KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination
from trip_pilot.ports import LLM
from trip_pilot.rag.chunking import parse_frontmatter, split_into_chunks

log = logging.getLogger(__name__)


async def build_index(session: AsyncSession, knowledge_dir: Path) -> None:
    """Загрузить Markdown-документы и их фрагменты в kb_document / kb_chunk."""
    paths = sorted(knowledge_dir.glob("*.md")) if knowledge_dir.is_dir() else []
    total_chunks = 0
    changed_documents = 0
    skipped_documents = 0

    for path in paths:
        raw_content = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        metadata, body = parse_frontmatter(raw_content)
        title = metadata["title"]
        doc_type = metadata["doc_type"]
        destination_slug = metadata["destination"]

        destination_result = await session.execute(
            select(Destination).where(Destination.slug == destination_slug)
        )
        destination = destination_result.scalar_one_or_none()

        if destination is None:
            raise ValueError(
                f"Направление {destination_slug!r} из файла {path} "
                "не найдено в таблице destination"
            )

        document_result = await session.execute(
            select(KbDocument).where(
                KbDocument.destination_id == destination.id,
                KbDocument.title == title,
                KbDocument.doc_type == doc_type,
            )
        )
        document = document_result.scalar_one_or_none()

        chunks = split_into_chunks(
            title=title,
            body=body,
            months=metadata["months"],
            tags=metadata["tags"],
        )

        if document is not None and document.content_hash == content_hash:
            # Документ не менялся: оставляем существующие фрагменты без изменений.
            total_chunks += len(chunks)
            skipped_documents += 1
            continue

        if document is None:
            document = KbDocument(
                id=uuid.uuid4(),
                source=metadata["source"],
                source_url=None,
                title=title,
                doc_type=doc_type,
                destination_id=destination.id,
                is_synthetic=metadata["source"] == "synthetic",
                content_hash=content_hash,
            )
            session.add(document)
            await session.flush()
        else:
            # Удаляем старые фрагменты перед заменой содержимого документа.
            await session.execute(
                delete(KbChunk).where(KbChunk.document_id == document.id)
            )
            document.source = metadata["source"]
            document.source_url = None
            document.destination_id = destination.id
            document.is_synthetic = metadata["source"] == "synthetic"
            document.content_hash = content_hash

        for chunk in chunks:
            session.add(
                KbChunk(
                    document_id=document.id,
                    parent_id=None,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                    meta=chunk.meta,
                    embedding=None,
                    embedding_model=None,
                )
            )

        total_chunks += len(chunks)
        changed_documents += 1

    log.info(
        "RAG: документов: %d, фрагментов: %d "
        "(добавлено/обновлено документов: %d, без изменений: %d)",
        len(paths),
        total_chunks,
        changed_documents,
        skipped_documents,
    )


async def embed_index(session: AsyncSession, llm: LLM) -> None:
    """Эмбеддинги фрагментов (этап 1). Заглушка лида: пока ничего не делает.

    rag заменяет тело (задача 4 в tasks/rag.md). Без ключа — пропуск, а не падение bootstrap.
    """
