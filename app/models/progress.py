from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VideoProgress(Base):
    """
    Per-user learning checkpoints for one video.

    ``completion_percentage`` is derived from the six activity flags (equal weight) and stored
    for fast dashboard reads.
    """

    __tablename__ = "video_progress"
    __table_args__ = (UniqueConstraint("user_id", "video_id", name="uq_video_progress_user_video"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)

    transcript_viewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_viewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mcq_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    short_questions_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flashcards_viewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    chatbot_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    completion_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
