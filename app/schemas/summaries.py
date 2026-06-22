from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.datetime_support import UtcCreatedAtMixin


class SummaryOut(UtcCreatedAtMixin):
    id: int
    video_id: int
    transcript_id: int
    summary_text: str
    summary_type: str
    status: str
    created_at: datetime


class SummaryGenerateResponse(BaseModel):
    message: str = Field(default="Summary generated")
    summary: SummaryOut

