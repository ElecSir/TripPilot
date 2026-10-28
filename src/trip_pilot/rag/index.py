"""Индексация Markdown-базы знаний в PostgreSQL."""

import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.knowledge import EMBEDDING_DIM, KbChunk, KbDocument
from trip_pilot.adapters.db.reference import Destination
from trip_pilot.config import Settings
from trip_pilot.ports import LLM, LLMUnavailable
from trip_pilot.rag.chunking import parse_frontmatter, split_into_chunks

log = logging.getLogger(__name__)


async def build_index(session: AsyncSession, knowledge_dir: Path) -> None:
    """Загрузить Markdown-документы и их фрагменты в kb_document / kb_chunk."""
    paths = sorted(knowledge_dir.rglob("*.md")) if knowledge_dir.is_dir() else []

    if not knowledge_dir.is_dir():
        log.info("RAG: папка знаний %s не найдена, индексация пропущена", knowledge_dir)
        return

    # Удаляем из индекса документы, файлы которых больше не существуют.
    current_filenames = {
        path.relative_to(knowledge_dir).as_posix()
        for path in paths
    }

    indexed_result = await session.execute(
        select(KbDocument).where(
            KbDocument.source_url.is_not(None),
            KbDocument.doc_type.in_(["destination", "rules"]),
        )
    )
    indexed_documents = indexed_result.scalars().all()

    for document in indexed_documents:
        if document.source_url not in current_filenames:
            await session.execute(
                delete(KbChunk).where(KbChunk.document_id == document.id)
            )
            await session.execute(
                delete(KbDocument).where(KbDocument.id == document.id)
            )

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
        destination = None

        if destination_slug is not None:
            destination_result = await session.execute(
                select(Destination).where(Destination.slug == destination_slug)
            )
            destination = destination_result.scalar_one_or_none()

            if destination is None:
                raise ValueError(
                    f"Направление {destination_slug!r} из файла {path} "
                    "не найдено в таблице destination"
                )
        elif doc_type != "rules":
            raise ValueError(
                f"Документ {path} без destination должен иметь doc_type='rules'"
            )

        source_url = path.relative_to(knowledge_dir).as_posix()

        destination_condition = (
            KbDocument.destination_id.is_(None)
            if destination is None
            else KbDocument.destination_id == destination.id
        )

        document_result = await session.execute(
            select(KbDocument).where(
                or_(
                    KbDocument.source_url == source_url,
                    (
                        KbDocument.source_url.is_(None)
                        & destination_condition
                        & (KbDocument.doc_type == doc_type)
                        & (KbDocument.source == metadata["source"])
                    ),
                )
            )
        )
        document = document_result.scalar_one_or_none()

        chunks = split_into_chunks(
            title=title,
            body=body,
            months=metadata["months"],
            tags=metadata["tags"],
        )

        if document is not None:
            document.source = metadata["source"]
            document.source_url = source_url
            document.title = title
            document.doc_type = doc_type
            document.destination_id = destination.id if destination else None
            document.is_synthetic = metadata["source"] == "synthetic"

        if document is not None and document.content_hash == content_hash:
            # Документ не менялся: оставляем существующие фрагменты без изменений.
            total_chunks += len(chunks)
            skipped_documents += 1
            continue

        if document is None:
            document = KbDocument(
                id=uuid.uuid4(),
                source=metadata["source"],
                source_url=source_url,
                title=title,
                doc_type=doc_type,
                destination_id=destination.id if destination else None,
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
            document.source_url = source_url
            document.destination_id = destination.id if destination else None
            document.is_synthetic = metadata["source"] == "synthetic"
            document.content_hash = content_hash
            document.title = title
            document.doc_type = doc_type

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
    """Заполнить эмбеддинги фрагментов базы знаний."""

    if not llm.enabled:
        log.info("RAG: LLM отключена, генерация эмбеддингов пропущена")
        return

    settings = Settings()
    model = settings.embeddings_model

    if not model:
        log.info("RAG: модель эмбеддингов не задана, индексация пропущена")
        return

    result = await session.execute(
        select(KbChunk).where(
            or_(
                KbChunk.embedding.is_(None),
                KbChunk.embedding_model != model,
                KbChunk.embedding_model.is_(None),
            )
        )
    )
    chunks = result.scalars().all()

    if not chunks:
        log.info("RAG: все фрагменты уже имеют актуальные эмбеддинги")
        return

    processed = 0

    batch_size = 16

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]

        try:
            vectors = await llm.embed([chunk.content for chunk in batch])
        except LLMUnavailable as error:
            log.warning("RAG: эмбеддинги недоступны, индексация пропущена: %s", error)
            return

        if len(vectors) != len(batch):
            log.warning("RAG: число эмбеддингов не совпало с числом фрагментов")
            return

        if any(len(vector) != EMBEDDING_DIM for vector in vectors):
            log.warning(
                "RAG: размерность эмбеддинга не равна %d; индексация пропущена",
                EMBEDDING_DIM,
            )
            return

        for chunk, vector in zip(batch, vectors, strict=False):
            chunk.embedding = vector
            chunk.embedding_model = model

        await session.flush()
        processed += len(batch)

    log.info("RAG: создано эмбеддингов: %d, модель: %s", processed, model)
