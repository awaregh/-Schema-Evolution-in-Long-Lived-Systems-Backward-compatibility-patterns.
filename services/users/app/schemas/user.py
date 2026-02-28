"""
Pydantic schemas for the Users service.

Schema evolution strategy
--------------------------
V1  – uses ``first_name`` / ``last_name`` (original names).
V2  – uses ``given_name`` / ``family_name`` (renamed fields); also accepts
      ``first_name`` / ``last_name`` as optional aliases so that V1 clients
      are still served correctly (Tolerant Reader pattern).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


# ── V1 schemas ────────────────────────────────────────────────────────────────


class UserBaseV1(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)
    status: str = Field("active", max_length=20)
    plan: str = Field("free", max_length=50)


class UserCreateV1(UserBaseV1):
    pass


class UserResponseV1(UserBaseV1):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── V2 schemas ────────────────────────────────────────────────────────────────


class UserBaseV2(BaseModel):
    # Canonical v2 name fields
    given_name: Optional[str] = Field(None, max_length=100)
    family_name: Optional[str] = Field(None, max_length=100)

    # Accepted for backward compatibility with V1 clients (tolerant reader)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)

    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)
    status: str = Field("active", max_length=20)
    plan: str = Field("free", max_length=50)

    @model_validator(mode="after")
    def _backfill_given_name(self) -> "UserBaseV2":
        """Tolerant reader: promote v1 fields → v2 fields when v2 fields are absent."""
        if not self.given_name and self.first_name:
            self.given_name = self.first_name
        if not self.family_name and self.last_name:
            self.family_name = self.last_name
        return self


class UserCreateV2(UserBaseV2):
    pass


class UserResponseV2(BaseModel):
    id: uuid.UUID
    given_name: Optional[str]
    family_name: Optional[str]
    # Also expose v1 fields so mixed-version clients can still read them
    first_name: Optional[str]
    last_name: Optional[str]
    email: EmailStr
    phone: Optional[str]
    status: str
    plan: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
