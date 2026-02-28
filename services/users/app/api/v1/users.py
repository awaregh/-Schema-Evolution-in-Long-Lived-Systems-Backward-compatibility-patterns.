"""
API v1 – Users router.

Backward-compatibility contract
--------------------------------
* Reads  : tolerant reader – returns ``given_name`` in the ``first_name``
           field when the feature flag is enabled and ``given_name`` is
           populated (expand phase).
* Writes : dual-write – always writes ``first_name``; also writes
           ``given_name`` when ``FEATURE_FLAG_GIVEN_NAME`` is enabled.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreateV1, UserResponseV1

router = APIRouter(prefix="/api/v1/users", tags=["users-v1"])


# ── helpers ───────────────────────────────────────────────────────────────────


def _apply_dual_write(user: User, first_name: str, last_name: str) -> None:
    """Populate v2 shadow columns and bump schema_version when the feature flag is on."""
    if settings.FEATURE_FLAG_GIVEN_NAME:
        user.given_name = first_name
        user.family_name = last_name
        user.schema_version = 2


def _get_or_404(user_id: uuid.UUID, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _to_v1_response(user: User) -> UserResponseV1:
    """Tolerant reader: surface given_name in first_name slot when available."""
    first = user.given_name if (settings.FEATURE_FLAG_GIVEN_NAME and user.given_name) else user.first_name
    last = user.family_name if (settings.FEATURE_FLAG_GIVEN_NAME and user.family_name) else user.last_name
    return UserResponseV1(
        id=user.id,
        first_name=first or "",
        last_name=last or "",
        email=user.email,
        phone=user.phone,
        status=user.status,
        plan=user.plan,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# ── endpoints ─────────────────────────────────────────────────────────────────


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "v1"}


@router.get("/", response_model=List[UserResponseV1])
def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[UserResponseV1]:
    stmt = (
        select(User)
        .where(User.deleted_at.is_(None))
        .offset(skip)
        .limit(limit)
        .order_by(User.created_at.desc())
    )
    users = db.execute(stmt).scalars().all()
    return [_to_v1_response(u) for u in users]


@router.get("/{user_id}", response_model=UserResponseV1)
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> UserResponseV1:
    return _to_v1_response(_get_or_404(user_id, db))


@router.post("/", response_model=UserResponseV1, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateV1, db: Session = Depends(get_db)) -> UserResponseV1:
    user = User(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        status=payload.status,
        plan=payload.plan,
        schema_version=1,
    )
    # Dual-write: populate v2 shadow columns when feature flag is active
    _apply_dual_write(user, payload.first_name, payload.last_name)

    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_v1_response(user)


@router.put("/{user_id}", response_model=UserResponseV1)
def update_user(
    user_id: uuid.UUID,
    payload: UserCreateV1,
    db: Session = Depends(get_db),
) -> UserResponseV1:
    user = _get_or_404(user_id, db)
    user.first_name = payload.first_name
    user.last_name = payload.last_name
    user.email = payload.email
    user.phone = payload.phone
    user.status = payload.status
    user.plan = payload.plan

    _apply_dual_write(user, payload.first_name, payload.last_name)

    db.commit()
    db.refresh(user)
    return _to_v1_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    user = _get_or_404(user_id, db)
    user.deleted_at = datetime.now(timezone.utc)
    db.commit()
