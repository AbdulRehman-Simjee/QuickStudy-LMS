from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.datetime_support import UtcCreatedAtMixin


class TranscriptOut(UtcCreatedAtMixin):
    id: int
    video_id: int
    audio_id: int
    transcript_text: str
    language_detected: str | None
    status: str
    created_at: datetime


class TranscriptGenerateResponse(BaseModel):
    message: str = Field(default="Transcript generated")
    transcript: TranscriptOut

