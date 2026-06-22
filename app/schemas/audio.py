from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.datetime_support import UtcCreatedAtMixin


class AudioOut(UtcCreatedAtMixin):
    id: int
    video_id: int
    filename: str
    file_path: str
    file_size: int
    duration: float | None
    status: str
    created_at: datetime


class AudioExtractResponse(BaseModel):
    message: str = Field(default="Audio extraction started")
    audio: AudioOut

