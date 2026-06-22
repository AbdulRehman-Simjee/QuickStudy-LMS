from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SummaryStatus(str, enum.Enum):
    processing = "processing"
    done = "done"
    failed = "failed"


class SummaryType(str, enum.Enum):
    short = "short"
    detailed = "detailed"


class Summary(Base):
    """
    AI-generated summary for a video's transcript.
    """

    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True)

    summary_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary_type: Mapped[str] = mapped_column(String(20), nullable=False, default=SummaryType.short.value)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SummaryStatus.processing.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

