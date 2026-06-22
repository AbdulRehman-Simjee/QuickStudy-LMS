from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole
from app.schemas.datetime_support import UtcCreatedAtMixin


class SignupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    # bcrypt only uses the first 72 bytes of a password; we enforce <= 72 bytes.
    password: str = Field(min_length=8, max_length=72)
    role: UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserPublic(UtcCreatedAtMixin):
    id: int
    full_name: str
    email: EmailStr
    role: UserRole
    plan: str
    avatar_url: str | None = None
    pro_expires_at: datetime | None = None
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class MessageResponse(BaseModel):
    message: str

