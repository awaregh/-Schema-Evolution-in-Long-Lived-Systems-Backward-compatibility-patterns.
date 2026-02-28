import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """
    Central users table designed for schema-evolution research.

    Column lifecycle
    ----------------
    v1 (baseline)  : first_name, last_name, email, phone, status, plan,
                     meta, created_at, updated_at, deleted_at, schema_version
    v2 (expand)    : given_name, family_name added as nullable shadow columns;
                     metadata_json added as the canonical replacement for meta.
                     Both old and new columns coexist (expand phase).
    v3 (contract)  : meta / first_name / last_name would be dropped once all
                     readers migrate (not yet applied).
    """

    __tablename__ = "users"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )

    # ── v1 name columns ──────────────────────────────────────────────────────
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── v2 shadow name columns (expand phase) ────────────────────────────────
    given_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Contact / account ────────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")

    # ── Metadata columns (rename migration: meta → metadata_json) ────────────
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Audit / lifecycle ─────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
        onupdate=_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Tracks which schema version last wrote this row
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r} schema_version={self.schema_version}>"
