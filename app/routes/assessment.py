from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.video import Video
from app.schemas.assessment import McqSubmitRequest, McqSubmitResponse, ShortSubmitRequest, ShortSubmitResponse
from app.schemas.progress_dashboard import ProgressUpdateIn
from app.services.assessment_service import submit_mcq_assessment, submit_short_assessment
from app.services.progress_service import update_progress

router = APIRouter(prefix="/assessment", tags=["Assessment"])


def _require_owned_video(db: Session, *, video_id: int, user_id: int) -> None:
    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")


@router.post(
    "/submit/mcq/{video_id}",
    response_model=McqSubmitResponse,
    response_model_exclude_none=True,
)
def submit_mcq(
    video_id: int,
    body: McqSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> McqSubmitResponse:
    """
    Submit MCQ answers for a video (owner-only).

    The body must include **exactly one** answer for **every** stored MCQ for this ``video_id``.
    Replaces any previous MCQ attempts for this user and video with this submission.
    """

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    pairs = [(a.question_id, a.selected_option) for a in body.answers]
    response = submit_mcq_assessment(db, user_id=current_user.id, video_id=video_id, answers=pairs)
    update_progress(
        db,
        user_id=current_user.id,
        video_id=video_id,
        payload=ProgressUpdateIn(mcq_attempted=True),
    )
    return response


@router.post("/submit/short/{video_id}", response_model=ShortSubmitResponse)
def submit_short(
    video_id: int,
    body: ShortSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShortSubmitResponse:
    """
    Submit short answers for AI marking (gpt-4o-mini), owner-only.

    One text answer per stored short question. Previous attempts for this user and video are replaced.
    """

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    pairs = [(a.question_id, a.student_answer) for a in body.answers]
    response = submit_short_assessment(db, user_id=current_user.id, video_id=video_id, answers=pairs)
    update_progress(
        db,
        user_id=current_user.id,
        video_id=video_id,
        payload=ProgressUpdateIn(short_questions_attempted=True),
    )
    return response
