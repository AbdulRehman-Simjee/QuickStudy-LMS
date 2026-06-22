from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.progress_dashboard import VideoResultsOut
from app.services.results_service import get_video_results

router = APIRouter(prefix="/results", tags=["Results"])


@router.get("/{video_id}", response_model=VideoResultsOut)
def get_results(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoResultsOut:
    """
    Full results bundle for one video: metadata, transcript, summary, attempts, flashcards, progress flags.
    """

    return get_video_results(db, user_id=current_user.id, video_id=video_id)
