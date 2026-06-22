from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.video import Video
from app.schemas.progress_dashboard import ProgressUpdateIn
from app.schemas.transcripts import TranscriptGenerateResponse, TranscriptOut
from app.services.progress_service import update_progress
from app.services.transcript_service import generate_transcript, get_transcript_for_video

router = APIRouter(prefix="/transcripts", tags=["Transcripts"])


def _to_out(t) -> TranscriptOut:
    return TranscriptOut(
        id=t.id,
        video_id=t.video_id,
        audio_id=t.audio_id,
        transcript_text=t.transcript_text,
        language_detected=t.language_detected,
        status=t.status,
        created_at=t.created_at,
    )


@router.post("/generate/{video_id}", response_model=TranscriptGenerateResponse)
def generate(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TranscriptGenerateResponse:
    """
    Generate a transcript for the given video (owner-only).
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    transcript = generate_transcript(db, video_id=video_id)
    return TranscriptGenerateResponse(transcript=_to_out(transcript))


@router.get("/{video_id}", response_model=TranscriptOut)
def get_transcript(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TranscriptOut:
    """
    Get transcript for a video (owner-only).
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    transcript = get_transcript_for_video(db, video_id=video_id)
    if transcript is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found")

    update_progress(
        db,
        user_id=current_user.id,
        video_id=video_id,
        payload=ProgressUpdateIn(transcript_viewed=True),
    )
    return _to_out(transcript)

