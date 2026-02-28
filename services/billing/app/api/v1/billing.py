"""
API v1 – Billing router.

Backward-compatibility contract
---------------------------------
* V1 write path  : writes ``amount_cents``; dual-writes ``amount`` (Decimal)
                   when ``schema_version >= 2`` to prepare for the type-change
                   migration (expand / contract).
* V1 read path   : tolerant reader – returns both ``amount_cents`` and
                   ``amount`` so that v2 consumers can read the new field
                   without a coordinated cutover.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.billing import Invoice, Subscription
from app.schemas.billing import (
    InvoiceCreateV1,
    InvoiceResponseV1,
    SubscriptionCreateV1,
    SubscriptionResponseV1,
)

router = APIRouter(tags=["billing-v1"])

# ── helpers ───────────────────────────────────────────────────────────────────


def _dual_write_amount(obj: Subscription | Invoice, amount_cents: int) -> None:
    """Populate the v2 ``amount`` column when the schema is at v2 or higher."""
    schema_v = int(settings.SERVICE_VERSION.lstrip("v") or 1)
    if schema_v >= 2:
        obj.amount = Decimal(amount_cents) / 100
        obj.schema_version = 2


def _get_subscription_or_404(sub_id: uuid.UUID, db: Session) -> Subscription:
    obj = db.get(Subscription, sub_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found"
        )
    return obj


def _get_invoice_or_404(inv_id: uuid.UUID, db: Session) -> Invoice:
    obj = db.get(Invoice, inv_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found"
        )
    return obj


# ── health ────────────────────────────────────────────────────────────────────


@router.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "version": "v1"}


# ── subscriptions ─────────────────────────────────────────────────────────────


@router.get("/api/v1/subscriptions", response_model=List[SubscriptionResponseV1])
def list_subscriptions(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[SubscriptionResponseV1]:
    stmt = (
        select(Subscription)
        .offset(skip)
        .limit(limit)
        .order_by(Subscription.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


@router.get(
    "/api/v1/subscriptions/{subscription_id}",
    response_model=SubscriptionResponseV1,
)
def get_subscription(
    subscription_id: uuid.UUID, db: Session = Depends(get_db)
) -> Subscription:
    return _get_subscription_or_404(subscription_id, db)


@router.post(
    "/api/v1/subscriptions",
    response_model=SubscriptionResponseV1,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    payload: SubscriptionCreateV1, db: Session = Depends(get_db)
) -> Subscription:
    sub = Subscription(
        user_id=payload.user_id,
        plan=payload.plan,
        status=payload.status,
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        billing_cycle=payload.billing_cycle,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        next_billing_date=payload.next_billing_date,
        schema_version=1,
    )
    # Dual-write: populate v2 amount column when running at schema_version >= 2
    _dual_write_amount(sub, payload.amount_cents)

    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


# ── invoices ──────────────────────────────────────────────────────────────────


@router.get("/api/v1/invoices", response_model=List[InvoiceResponseV1])
def list_invoices(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[InvoiceResponseV1]:
    stmt = (
        select(Invoice)
        .offset(skip)
        .limit(limit)
        .order_by(Invoice.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/api/v1/invoices/{invoice_id}", response_model=InvoiceResponseV1)
def get_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db)) -> Invoice:
    return _get_invoice_or_404(invoice_id, db)


@router.post(
    "/api/v1/invoices",
    response_model=InvoiceResponseV1,
    status_code=status.HTTP_201_CREATED,
)
def create_invoice(
    payload: InvoiceCreateV1, db: Session = Depends(get_db)
) -> Invoice:
    invoice = Invoice(
        subscription_id=payload.subscription_id,
        user_id=payload.user_id,
        invoice_number=payload.invoice_number,
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        status=payload.status,
        issued_at=payload.issued_at,
        due_at=payload.due_at,
        paid_at=payload.paid_at,
        line_items=payload.line_items,
        schema_version=1,
    )
    _dual_write_amount(invoice, payload.amount_cents)

    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice
