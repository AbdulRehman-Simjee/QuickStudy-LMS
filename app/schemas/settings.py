from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.user import UserRole


_FULL_NAME_PATTERN = re.compile(r"^[a-zA-Z ]+$")


class SettingsProfileOut(BaseModel):
    full_name: str
    email: EmailStr
    role: UserRole
    plan: str
    avatar_url: str | None = None
    created_at: datetime


class SettingsAvatarUrlOut(BaseModel):
    avatar_url: str


class SettingsProfilePatchIn(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=200)

    @field_validator("full_name")
    @classmethod
    def letters_and_spaces_only(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        if not _FULL_NAME_PATTERN.fullmatch(s):
            raise ValueError("Full name may only contain letters and spaces.")
        return s


class SettingsChangePasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=72)
    confirm_password: str = Field(..., min_length=8, max_length=72)

    @model_validator(mode="after")
    def new_matches_confirm(self) -> SettingsChangePasswordIn:
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation must match.")
        return self


class SettingsMessageOut(BaseModel):
    message: str
