from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(str, enum.Enum):
    """
    User role within the LMS.
    """

    student = "student"
    teacher = "teacher"


class UserPlan(str, enum.Enum):
    free = "free"
    pro = "pro"


class User(Base):
    """
    Core user entity for authentication/authorization.

    Security note:
    - The `password` column stores a *hash*, never a plaintext password.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # Store hashed password; the DB column name stays as "password" to match the requirement.
    password_hash: Mapped[str] = mapped_column("password", String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(String(20), nullable=False, default=UserRole.student.value)
    plan: Mapped[UserPlan] = mapped_column(String(20), nullable=False, default=UserPlan.free.value)

    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    pro_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

