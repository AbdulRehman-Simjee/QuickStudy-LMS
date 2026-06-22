from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.summary import Summary, SummaryType
from app.models.user import User
from app.models.video import Video
from app.services.plan_service import ensure_detailed_summary_allowed
from app.schemas.progress_dashboard import ProgressUpdateIn
from app.schemas.summaries import SummaryGenerateResponse, SummaryOut
from app.services.progress_service import update_progress
from app.services.summarization_service import generate_summary

router = APIRouter(prefix="/summaries", tags=["Summaries"])


def _to_out(s: Summary) -> SummaryOut:
    return SummaryOut(
        id=s.id,
        video_id=s.video_id,
        transcript_id=s.transcript_id,
        summary_text=s.summary_text,
        summary_type=s.summary_type,
        status=s.status,
        created_at=s.created_at,
    )


@router.post("/generate/{video_id}", response_model=SummaryGenerateResponse)
def generate(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    summary_type: str = Query(default=SummaryType.short.value, pattern="^(short|detailed)$"),
) -> SummaryGenerateResponse:
    """
    Generate an English-only summary for the video's transcript (owner-only).
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    ensure_detailed_summary_allowed(current_user, summary_type=summary_type)

    summary = generate_summary(db, video_id=video_id, summary_type=summary_type)
    return SummaryGenerateResponse(summary=_to_out(summary))


@router.get("/{video_id}", response_model=SummaryOut)
def get_summary(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SummaryOut:
    """
    Get summary for a video (owner-only).
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")
    update_progress(
        db,
        user_id=current_user.id,
        video_id=video_id,
        payload=ProgressUpdateIn(summary_viewed=True),
    )
    return _to_out(summary)

