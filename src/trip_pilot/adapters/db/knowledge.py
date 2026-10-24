"""База знаний RAG: документы и фрагменты. Зона: rag."""

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from trip_pilot.adapters.db.base import Base

# Зависит от модели эмбеддингов; смена модели = новая миграция + переиндексация.
EMBEDDING_DIM = 1024


class KbDocument(Base):
    """Документ базы знаний (путеводитель, правило, политика отеля, отзыв)."""

    __tablename__ = "kb_document"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(Text)
    destination_id: Mapped[int | None] = mapped_column(ForeignKey("destination.id"))
    lang: Mapped[str] = mapped_column(Text, server_default=text("'ru'"))
    is_synthetic: Mapped[bool]
    content_hash: Mapped[str] = mapped_column(Text, unique=True)


class KbChunk(Base):
    __tablename__ = "kb_chunk"
    __table_args__ = (
        Index("ix_kb_chunk_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_kb_chunk_meta",
            "meta",
            postgresql_using="gin",
            postgresql_ops={"meta": "jsonb_path_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kb_document.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("kb_chunk.id"))
    heading_path: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian', content)", persisted=True)
    )
