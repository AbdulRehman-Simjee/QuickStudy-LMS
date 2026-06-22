from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.video import Video
from app.schemas.progress_dashboard import ProgressUpdateIn, ProgressUpdateResponse, VideoProgressOut
from app.services.progress_service import get_progress_view, serialize_progress, update_progress

router = APIRouter(prefix="/progress", tags=["Progress"])


def _require_owned_video(db: Session, *, video_id: int, user_id: int) -> None:
    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")


@router.post("/update/{video_id}", response_model=ProgressUpdateResponse)
def update_video_progress(
    video_id: int,
    body: ProgressUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProgressUpdateResponse:
    """
    Merge activity flags for this video. Only fields present in the JSON body are updated.

    ``completion_percentage`` is recalculated as the percentage of the six flags that are True.
    """

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    row = update_progress(db, user_id=current_user.id, video_id=video_id, payload=body)
    return ProgressUpdateResponse(progress=serialize_progress(row))


@router.get("/{video_id}", response_model=VideoProgressOut)
def get_video_progress(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoProgressOut:
    """Return progress for this video, or a zeroed snapshot if none has been recorded yet."""

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    return get_progress_view(db, user_id=current_user.id, video_id=video_id)
