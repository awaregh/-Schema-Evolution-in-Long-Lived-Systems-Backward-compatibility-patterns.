"""001_baseline

Baseline migration – creates the ``users`` table with ALL columns,
including both v1 name columns (``first_name`` / ``last_name``) and the
v2 shadow columns (``given_name`` / ``family_name``) already present.

This "expand-first" baseline means the database schema is ready to support
v1 and v2 application code simultaneously from day one, demonstrating the
*expand / contract* pattern at the database level.

Revision ID : 001_baseline
Revises     : (none – first migration)
Create Date : 2024-01-01 00:00:00.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic metadata
revision: str = "001_baseline"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        # ── Primary key ───────────────────────────────────────────────────────
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # ── v1 name columns ───────────────────────────────────────────────────
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        # ── v2 shadow name columns (expand phase) ─────────────────────────────
        sa.Column("given_name", sa.String(100), nullable=True),
        sa.Column("family_name", sa.String(100), nullable=True),
        # ── Contact / account ─────────────────────────────────────────────────
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        # ── Metadata columns (rename: meta → metadata_json) ───────────────────
        sa.Column("meta", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        # ── Audit / lifecycle ─────────────────────────────────────────────────
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # Tracks which schema version last wrote this row
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Partial index – quickly find rows that still need v2 backfill
    op.create_index(
        "ix_users_given_name_null",
        "users",
        ["id"],
        unique=False,
        postgresql_where=sa.text("given_name IS NULL AND deleted_at IS NULL"),
    )

    # ── updated_at auto-update trigger ────────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at;")
    op.drop_index("ix_users_given_name_null", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
