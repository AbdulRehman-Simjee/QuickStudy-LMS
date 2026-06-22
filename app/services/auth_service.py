from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.utils.security import hash_password, verify_password


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def create_user(
    db: Session,
    *,
    full_name: str,
    email: str,
    password: str,
    role: UserRole,
) -> User:
    """
    Create a new user with a bcrypt-hashed password.
    """

    user = User(
        full_name=full_name,
        email=email.lower().strip(),
        password_hash=hash_password(password),
        role=role.value,
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email.lower().strip())
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user

