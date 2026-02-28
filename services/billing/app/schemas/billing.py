"""
Pydantic schemas for the Billing service.

Schema evolution strategy
--------------------------
V1 – monetary values expressed as integer cents (``amount_cents``).
V2 – monetary values expressed as Decimal (``amount``); demonstrates a
     type-change migration.  V2 create requests still accept ``amount_cents``
     for backward compatibility.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# ── Shared base ───────────────────────────────────────────────────────────────


class _SubscriptionBase(BaseModel):
    user_id: uuid.UUID
    plan: str = Field(..., max_length=50)
    status: str = Field("active", max_length=20)
    currency: str = Field("USD", max_length=3)
    billing_cycle: str = Field("monthly", max_length=20)
    started_at: datetime
    ended_at: Optional[datetime] = None
    next_billing_date: Optional[date] = None


class _InvoiceBase(BaseModel):
    subscription_id: uuid.UUID
    user_id: uuid.UUID
    invoice_number: str = Field(..., max_length=50)
    currency: str = Field("USD", max_length=3)
    status: str = Field("pending", max_length=20)
    issued_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    line_items: Optional[Any] = None


# ── V1 schemas (amount_cents) ─────────────────────────────────────────────────


class SubscriptionCreateV1(_SubscriptionBase):
    """V1 create request – caller provides amount as integer cents."""

    amount_cents: int = Field(..., ge=0)


class SubscriptionResponseV1(_SubscriptionBase):
    id: uuid.UUID
    amount_cents: int
    schema_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceCreateV1(_InvoiceBase):
    amount_cents: int = Field(..., ge=0)


class InvoiceResponseV1(_InvoiceBase):
    id: uuid.UUID
    amount_cents: int
    schema_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── V2 schemas (amount as Decimal) ────────────────────────────────────────────


class SubscriptionCreateV2(_SubscriptionBase):
    """
    V2 create request – caller provides amount as Decimal.

    Also accepts ``amount_cents`` for backward compatibility with V1 callers
    (tolerant reader pattern).  If both are provided, ``amount`` takes
    precedence.
    """

    amount: Optional[Decimal] = Field(None, ge=0)
    amount_cents: Optional[int] = Field(None, ge=0)

    @model_validator(mode="after")
    def _normalise_amount(self) -> "SubscriptionCreateV2":
        if self.amount is None and self.amount_cents is not None:
            self.amount = Decimal(self.amount_cents) / 100
        if self.amount_cents is None and self.amount is not None:
            self.amount_cents = int(self.amount * 100)
        return self


class SubscriptionResponseV2(_SubscriptionBase):
    id: uuid.UUID
    amount: Optional[Decimal]
    amount_cents: int
    schema_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceCreateV2(_InvoiceBase):
    amount: Optional[Decimal] = Field(None, ge=0)
    amount_cents: Optional[int] = Field(None, ge=0)

    @model_validator(mode="after")
    def _normalise_amount(self) -> "InvoiceCreateV2":
        if self.amount is None and self.amount_cents is not None:
            self.amount = Decimal(self.amount_cents) / 100
        if self.amount_cents is None and self.amount is not None:
            self.amount_cents = int(self.amount * 100)
        return self


class InvoiceResponseV2(_InvoiceBase):
    id: uuid.UUID
    amount: Optional[Decimal]
    amount_cents: int
    schema_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
