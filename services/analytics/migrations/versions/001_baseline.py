"""001_baseline

Baseline migration – creates the ``event_logs`` and
``user_event_aggregates`` tables.

The ``event_logs`` table stores an append-only record of every domain event
received by the analytics service, carrying an ``event_version`` column so
that consumers can apply upcasting / downcasting strategies as the payload
schema evolves.

Revision ID : 001_baseline
Revises     : (none – first migration)
Create Date : 2024-01-01 00:00:00.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_baseline"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── event_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "event_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_version", sa.String(10), nullable=False, server_default="1.0"),
        sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("source_service", sa.String(50), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_event_logs_id", "event_logs", ["id"], unique=False)
    op.create_index("ix_event_logs_event_type", "event_logs", ["event_type"], unique=False)
    op.create_index("ix_event_logs_source_service", "event_logs", ["source_service"], unique=False)
    op.create_index("ix_event_logs_created_at", "event_logs", ["created_at"], unique=False)
    # Partial index – quickly find unprocessed events for the processor loop
    op.create_index(
        "ix_event_logs_unprocessed",
        "event_logs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("processed = false"),
    )

    # ── user_event_aggregates ─────────────────────────────────────────────────
    op.create_table(
        "user_event_aggregates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "event_type", "date", name="uq_user_event_date"),
    )
    op.create_index(
        "ix_user_event_aggregates_id", "user_event_aggregates", ["id"], unique=False
    )
    op.create_index(
        "ix_user_event_aggregates_user_id",
        "user_event_aggregates",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_event_aggregates_date",
        "user_event_aggregates",
        ["date"],
        unique=False,
    )

    # ── updated_at auto-update triggers ───────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION analytics_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("event_logs", "user_event_aggregates"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION analytics_set_updated_at();
            """
        )


def downgrade() -> None:
    for table in ("event_logs", "user_event_aggregates"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.execute("DROP FUNCTION IF EXISTS analytics_set_updated_at;")
    op.drop_index("ix_user_event_aggregates_date", table_name="user_event_aggregates")
    op.drop_index("ix_user_event_aggregates_user_id", table_name="user_event_aggregates")
    op.drop_index("ix_user_event_aggregates_id", table_name="user_event_aggregates")
    op.drop_table("user_event_aggregates")
    op.drop_index("ix_event_logs_unprocessed", table_name="event_logs")
    op.drop_index("ix_event_logs_created_at", table_name="event_logs")
    op.drop_index("ix_event_logs_source_service", table_name="event_logs")
    op.drop_index("ix_event_logs_event_type", table_name="event_logs")
    op.drop_index("ix_event_logs_id", table_name="event_logs")
    op.drop_table("event_logs")
