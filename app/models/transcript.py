from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TranscriptStatus(str, enum.Enum):
    processing = "processing"
    done = "done"
    failed = "failed"


class Transcript(Base):
    """
    Speech-to-text transcript for a video's extracted audio.
    """

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id: Mapped[int] = mapped_column(ForeignKey("audio.id", ondelete="CASCADE"), nullable=False, index=True)

    transcript_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language_detected: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TranscriptStatus.processing.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

