"""
SQLAlchemy ORM models for the Billing service.

Column lifecycle
----------------
v1 (baseline) : amount_cents (Integer) – stores monetary value as integer cents.
v2 (expand)   : amount (Numeric 10,2) added as a nullable shadow column that
                stores the decimal representation.  Both columns coexist so
                that v1 and v2 application code can run simultaneously
                (expand / contract pattern).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Subscription(Base):
    """
    Billing subscription for a user.

    Demonstrates integer-to-decimal type-change pattern:
      v1 clients read/write ``amount_cents``.
      v2 clients read/write ``amount`` (Decimal) and dual-write ``amount_cents``.
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    plan: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    # v1 monetary column – always written
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # v2 shadow column – written when schema_version >= 2 (type-change demo)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    billing_cycle: Mapped[str] = mapped_column(
        String(20), nullable=False, default="monthly"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_billing_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)

    # Tracks which schema version last wrote this row
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

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

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Subscription id={self.id} user_id={self.user_id} "
            f"plan={self.plan!r} status={self.status!r}>"
        )


class Invoice(Base):
    """
    Invoice issued for a subscription billing cycle.

    Follows the same integer-to-decimal type-change pattern as Subscription.
    """

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )

    # v1 monetary column
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # v2 shadow column
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_now,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Flexible line-items stored as JSON (e.g. [{description, quantity, unit_price}])
    line_items: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

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

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Invoice id={self.id} invoice_number={self.invoice_number!r} "
            f"status={self.status!r}>"
        )
