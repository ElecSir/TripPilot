"""ORM-модели. Наружу из adapters/db не выходят: репозитории отдают доменные модели.

Схема меняется только миграциями Alembic (migrations/), не руками в pgAdmin.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Зависит от модели эмбеддингов; смена модели = новая миграция + переиндексация.
EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


class Destination(Base):
    __tablename__ = "destination"
    __table_args__ = (
        Index(
            "ix_destination_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text)
    iata: Mapped[str | None] = mapped_column(String(3))
    lat: Mapped[float]
    lon: Mapped[float]
    timezone: Mapped[str] = mapped_column(Text)  # IANA-зона, например Europe/Moscow
    is_synthetic: Mapped[bool] = mapped_column(server_default=text("false"))


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_session.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KbDocument(Base):
    """Документ базы знаний RAG (путеводитель, правило, политика отеля, отзыв)."""

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
