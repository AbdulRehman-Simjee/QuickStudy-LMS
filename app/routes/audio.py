from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.video import Video
from app.schemas.audio import AudioExtractResponse, AudioOut
from app.services.audio_service import get_audio_for_video, request_audio_extraction
from app.services.video_processing_service import run_audio_then_transcript_background

router = APIRouter(prefix="/audio", tags=["Audio"])


def _to_audio_out(a) -> AudioOut:
    return AudioOut(
        id=a.id,
        video_id=a.video_id,
        filename=a.filename,
        file_path=a.file_path,
        file_size=a.file_size,
        duration=a.duration,
        status=a.status,
        created_at=a.created_at,
    )


@router.post("/extract/{video_id}", response_model=AudioExtractResponse, status_code=status.HTTP_202_ACCEPTED)
def extract_audio(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AudioExtractResponse:
    """
    Trigger audio extraction for an uploaded video.
    Owner-only access.
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    audio = request_audio_extraction(db, video_id=video_id)
    background_tasks.add_task(run_audio_then_transcript_background, video_id=video_id)

    return AudioExtractResponse(audio=_to_audio_out(audio))


@router.get("/{video_id}", response_model=AudioOut)
def get_audio(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AudioOut:
    """
    Get audio details for a given video (owner-only).
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    audio = get_audio_for_video(db, video_id=video_id)
    if audio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")

    return _to_audio_out(audio)

