from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VideoStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    done = "done"


class Video(Base):
    """
    Uploaded video metadata.

    - `duration` is stored in seconds (nullable until extracted by a background task).
    - `file_path` is the stored relative/absolute path used to locate the file on disk.
    """

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)

    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    file_size: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=VideoStatus.uploaded.value)

    youtube_url: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    transcript_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    summary_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

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

