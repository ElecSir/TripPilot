"""Расширения, справочник направлений, диалоги, схема базы знаний RAG

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    op.create_table(
        "destination",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("iata", sa.String(3), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_destination_name_trgm",
        "destination",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    op.create_table(
        "chat_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "chat_message",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_chat_message_session_id", "chat_message", ["session_id"])

    op.create_table(
        "kb_document",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("destination_id", sa.Integer(), sa.ForeignKey("destination.id"), nullable=True),
        sa.Column("lang", sa.Text(), nullable=False, server_default=sa.text("'ru'")),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False, unique=True),
    )
    op.create_table(
        "kb_chunk",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("kb_document.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("kb_chunk.id"), nullable=True),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "meta",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('russian', content)", persisted=True),
        ),
    )
    op.create_index("ix_kb_chunk_document_id", "kb_chunk", ["document_id"])
    op.create_index("ix_kb_chunk_tsv", "kb_chunk", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_kb_chunk_meta",
        "kb_chunk",
        ["meta"],
        postgresql_using="gin",
        postgresql_ops={"meta": "jsonb_path_ops"},
    )
    # HNSW-индекс по embedding добавим, когда фрагментов станет десятки тысяч:
    # до этого точный перебор занимает миллисекунды и точнее приближённого индекса.


def downgrade() -> None:
    op.drop_table("kb_chunk")
    op.drop_table("kb_document")
    op.drop_table("chat_message")
    op.drop_table("chat_session")
    op.drop_table("destination")
