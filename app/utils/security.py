from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using bcrypt.
    """

    password_bytes = password.encode("utf-8")
    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return password_hash.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.
    """

    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Covers malformed hashes / invalid salt versions.
        return False


def create_access_token(*, subject: str, expires_minutes: int | None = None) -> str:
    """
    Create a signed JWT access token.

    - `subject` is typically the user id (stored as a string).
    """

    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp_minutes = expires_minutes if expires_minutes is not None else settings.access_token_expire_minutes
    expire = now + timedelta(minutes=exp_minutes)

    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": expire}
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token. Raises `JWTError` if invalid/expired.
    """

    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"verify_aud": False},
    )

