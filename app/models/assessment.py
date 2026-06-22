from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MCQAttempt(Base):
    """
    One row per MCQ response in the user's latest submitted attempt for a video.

    On each new submission for the same (user_id, video_id), previous MCQAttempt rows
    are removed and replaced so the database holds the most recent attempt only.
    """

    __tablename__ = "mcq_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("mcqs.id", ondelete="CASCADE"), nullable=False, index=True)

    selected_option: Mapped[str] = mapped_column(String(1), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # One point per correct MCQ in this schema (0 or 1).
    score: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ShortQuestionAttempt(Base):
    """
    One row per short-answer response in the user's latest submitted attempt for a video.

    Scores are 0–5 per question (AI-marked against the stored model answer).
    Replaced wholesale on each new submit for (user_id, video_id), like MCQAttempt.
    """

    __tablename__ = "short_question_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("short_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    student_answer: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
