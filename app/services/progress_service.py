from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.progress import VideoProgress
from app.models.video import Video
from app.schemas.progress_dashboard import ProgressUpdateIn, VideoProgressOut

logger = logging.getLogger(__name__)

# Equal-weight completion: six independent activity flags.
_ACTIVITY_FIELDS: tuple[str, ...] = (
    "transcript_viewed",
    "summary_viewed",
    "mcq_attempted",
    "short_questions_attempted",
    "flashcards_viewed",
    "chatbot_used",
)


def compute_completion_percentage(row: VideoProgress) -> int:
    """Return 0–100 from how many of the six flags are True."""

    done = sum(1 for name in _ACTIVITY_FIELDS if getattr(row, name))
    return round(100 * done / len(_ACTIVITY_FIELDS))


def serialize_progress(row: VideoProgress) -> VideoProgressOut:
    """ORM row → API model (always persisted)."""

    return _to_out(row, user_id=row.user_id, video_id=row.video_id)


def _to_out(row: VideoProgress | None, *, user_id: int, video_id: int) -> VideoProgressOut:
    if row is None:
        return VideoProgressOut(
            id=None,
            user_id=user_id,
            video_id=video_id,
            transcript_viewed=False,
            summary_viewed=False,
            mcq_attempted=False,
            short_questions_attempted=False,
            flashcards_viewed=False,
            chatbot_used=False,
            completion_percentage=0,
            last_activity=None,
            created_at=None,
            updated_at=None,
        )
    return VideoProgressOut(
        id=row.id,
        user_id=row.user_id,
        video_id=row.video_id,
        transcript_viewed=row.transcript_viewed,
        summary_viewed=row.summary_viewed,
        mcq_attempted=row.mcq_attempted,
        short_questions_attempted=row.short_questions_attempted,
        flashcards_viewed=row.flashcards_viewed,
        chatbot_used=row.chatbot_used,
        completion_percentage=row.completion_percentage,
        last_activity=row.last_activity,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_progress_view(db: Session, *, user_id: int, video_id: int) -> VideoProgressOut:
    """Return stored progress or a zeroed snapshot (no row inserted)."""

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    row = db.scalar(
        select(VideoProgress).where(
            VideoProgress.user_id == user_id,
            VideoProgress.video_id == video_id,
        ),
    )
    return _to_out(row, user_id=user_id, video_id=video_id)


def update_progress(
    db: Session,
    *,
    user_id: int,
    video_id: int,
    payload: ProgressUpdateIn,
) -> VideoProgress:
    """
    Upsert progress and merge boolean flags from the payload (only explicit fields change).
    """

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    row = db.scalar(
        select(VideoProgress).where(
            VideoProgress.user_id == user_id,
            VideoProgress.video_id == video_id,
        ),
    )
    if row is None:
        row = VideoProgress(user_id=user_id, video_id=video_id)
        db.add(row)

    data = payload.model_dump(exclude_unset=True)
    activity_updates = {k: v for k, v in data.items() if k in _ACTIVITY_FIELDS and v is not None}
    if not activity_updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one activity flag to update (e.g. transcript_viewed).",
        )

    for key, value in activity_updates.items():
        setattr(row, key, value)

    row.last_activity = datetime.now(timezone.utc)
    row.completion_percentage = compute_completion_percentage(row)
    db.commit()
    db.refresh(row)
    logger.debug("Progress updated", extra={"video_id": video_id, "user_id": user_id, "pct": row.completion_percentage})
    return row


def list_progress_map_for_user(db: Session, *, user_id: int) -> dict[int, VideoProgress]:
    """video_id -> row for all progress rows owned by the user."""

    rows = db.scalars(select(VideoProgress).where(VideoProgress.user_id == user_id)).all()
    return {r.video_id: r for r in rows}
