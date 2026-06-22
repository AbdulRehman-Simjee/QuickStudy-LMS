from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.config import get_settings
from app.utils.files import ensure_dir

AVATAR_MAX_BYTES = 5 * 1024 * 1024
_ALLOWED_PIL_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


def avatars_dir() -> Path:
    return get_settings().uploads_dir / "avatars"


def avatar_public_path(user_id: int) -> str:
    """URL path served by StaticFiles mount at ``/uploads``."""

    return f"/uploads/avatars/{user_id}.jpg"


def remove_avatar_file(user_id: int) -> None:
    path = avatars_dir() / f"{user_id}.jpg"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


async def read_and_save_avatar_jpeg(*, user_id: int, upload: UploadFile) -> None:
    raw = await upload.read()
    if len(raw) > AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image must be 5MB or smaller.",
        )
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    try:
        img = Image.open(BytesIO(raw))
        fmt = (img.format or "").upper()
        if fmt == "JPG":
            fmt = "JPEG"
        if fmt not in _ALLOWED_PIL_FORMATS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Allowed formats: JPG, PNG, WebP.",
            )
        img.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file.",
        ) from None

    img = Image.open(BytesIO(raw))
    img = img.convert("RGB")

    d = avatars_dir()
    ensure_dir(d)
    dest = d / f"{user_id}.jpg"
    tmp = dest.with_suffix(".jpg.tmp")
    try:
        img.save(tmp, format="JPEG", quality=88, optimize=True)
        tmp.replace(dest)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save avatar.",
        ) from None
