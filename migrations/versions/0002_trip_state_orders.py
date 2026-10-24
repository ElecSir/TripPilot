"""Состояние плана поездки и заказы

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trip_state",
        sa.Column("session_id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Номер заказа: TP-<год>-<6 цифр>. Последовательности autogenerate не отслеживает.
    op.execute("CREATE SEQUENCE IF NOT EXISTS order_number_seq")
    op.create_table(
        "orders",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Text(), nullable=False),
        sa.Column("package", postgresql.JSONB(), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_orders_session_key"),
    )


def downgrade() -> None:
    op.drop_table("orders")
    op.execute("DROP SEQUENCE IF EXISTS order_number_seq")
    op.drop_table("trip_state")
