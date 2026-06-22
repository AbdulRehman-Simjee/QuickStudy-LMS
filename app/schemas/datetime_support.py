from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator


def ensure_utc_naive(dt: datetime | None) -> datetime | None:
    """
    SQLite often returns naive datetimes; treat as UTC for correct ISO-8601 JSON (+00:00).
    Frontend: use `new Date(isoString)` — the runtime shows local time. For Asia/Karachi explicitly:
    `Intl.DateTimeFormat('en-PK', { timeZone: 'Asia/Karachi', ... }).format(date)`.
    """
    if dt is None:
        return None
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class UtcCreatedUpdatedMixin(BaseModel):
    @field_validator("created_at", "updated_at", mode="before", check_fields=False)
    @classmethod
    def _created_updated_utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc_naive(v)


class UtcProgressTimestampsMixin(BaseModel):
    """Progress rows may include last_activity plus created/updated."""

    @field_validator("created_at", "updated_at", "last_activity", mode="before", check_fields=False)
    @classmethod
    def _progress_ts_utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc_naive(v)


class UtcCreatedAtMixin(BaseModel):
    @field_validator("created_at", mode="before", check_fields=False)
    @classmethod
    def _created_at_utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc_naive(v)


class UtcLastActivityOnlyMixin(BaseModel):
    @field_validator("last_activity", mode="before", check_fields=False)
    @classmethod
    def _last_activity_utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc_naive(v)
