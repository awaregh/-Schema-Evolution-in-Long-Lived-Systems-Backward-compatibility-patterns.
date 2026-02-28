"""
API v2 – Users router.

Schema-evolution contract
--------------------------
* Reads  : canonical v2 fields (``given_name`` / ``family_name``) are
           returned directly.  ``first_name`` / ``last_name`` are also
           present in the response so that V1 consumers can still read the
           payload (tolerant reader / additive change).
* Writes : always writes both v2 fields *and* the v1 shadow columns so that
           a rollback to v1 readers remains safe (dual-write).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreateV2, UserResponseV2

router = APIRouter(prefix="/api/v2/users", tags=["users-v2"])


# ── helpers ───────────────────────────────────────────────────────────────────


def _get_or_404(user_id: uuid.UUID, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _to_v2_response(user: User) -> UserResponseV2:
    """
    Resolve name fields with v2-first precedence and populate both sets of
    fields so mixed-version clients can read the response.
    """
    given = user.given_name or user.first_name
    family = user.family_name or user.last_name
    return UserResponseV2(
        id=user.id,
        given_name=given,
        family_name=family,
        first_name=given,
        last_name=family,
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
    return {"status": "ok", "version": "v2"}


@router.get("/", response_model=List[UserResponseV2])
def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[UserResponseV2]:
    stmt = (
        select(User)
        .where(User.deleted_at.is_(None))
        .offset(skip)
        .limit(limit)
        .order_by(User.created_at.desc())
    )
    users = db.execute(stmt).scalars().all()
    return [_to_v2_response(u) for u in users]


@router.get("/{user_id}", response_model=UserResponseV2)
def get_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> UserResponseV2:
    return _to_v2_response(_get_or_404(user_id, db))


@router.post("/", response_model=UserResponseV2, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateV2, db: Session = Depends(get_db)) -> UserResponseV2:
    user = User(
        # v2 canonical fields
        given_name=payload.given_name,
        family_name=payload.family_name,
        # v1 backward-compat shadow columns (dual-write for safe rollback)
        first_name=payload.given_name,
        last_name=payload.family_name,
        email=payload.email,
        phone=payload.phone,
        status=payload.status,
        plan=payload.plan,
        schema_version=2,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_v2_response(user)


@router.put("/{user_id}", response_model=UserResponseV2)
def update_user(
    user_id: uuid.UUID,
    payload: UserCreateV2,
    db: Session = Depends(get_db),
) -> UserResponseV2:
    user = _get_or_404(user_id, db)
    user.given_name = payload.given_name
    user.family_name = payload.family_name
    user.first_name = payload.given_name
    user.last_name = payload.family_name
    user.email = payload.email
    user.phone = payload.phone
    user.status = payload.status
    user.plan = payload.plan
    user.schema_version = 2

    db.commit()
    db.refresh(user)
    return _to_v2_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    user = _get_or_404(user_id, db)
    user.deleted_at = datetime.now(timezone.utc)
    db.commit()
