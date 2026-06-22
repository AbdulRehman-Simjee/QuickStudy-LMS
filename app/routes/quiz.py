from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.quiz import Flashcard, Mcq, ShortQuestion
from app.models.user import User
from app.models.video import Video
from app.schemas.progress_dashboard import ProgressUpdateIn
from app.services.plan_service import ensure_quiz_regeneration_allowed
from app.schemas.quiz import (
    FlashcardGenerateResponse,
    FlashcardListResponse,
    FlashcardOut,
    McqGenerateResponse,
    McqListResponse,
    McqOut,
    ShortQuestionGenerateResponse,
    ShortQuestionListResponse,
    ShortQuestionOut,
)
from app.services.progress_service import update_progress
from app.services.quiz_generation_service import (
    generate_flashcards_for_video,
    generate_mcqs_for_video,
    generate_short_questions_for_video,
)

router = APIRouter(prefix="/quiz", tags=["Quiz"])
logger = logging.getLogger(__name__)


def _require_owned_video(db: Session, *, video_id: int, user_id: int) -> None:
    """
    Enforce owner-only access: non-owners receive 404 to avoid leaking video existence.
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")


def _mcq_out(row: Mcq) -> McqOut:
    return McqOut(
        id=row.id,
        video_id=row.video_id,
        question=row.question,
        option_a=row.option_a,
        option_b=row.option_b,
        option_c=row.option_c,
        option_d=row.option_d,
        correct_answer=row.correct_answer,
        explanation=row.explanation,
        created_at=row.created_at,
    )


def _short_out(row: ShortQuestion) -> ShortQuestionOut:
    return ShortQuestionOut(
        id=row.id,
        video_id=row.video_id,
        question=row.question,
        model_answer=row.model_answer,
        created_at=row.created_at,
    )


def _flash_out(row: Flashcard) -> FlashcardOut:
    return FlashcardOut(
        id=row.id,
        video_id=row.video_id,
        front=row.front,
        back=row.back,
        created_at=row.created_at,
    )


# --- MCQ ---


@router.post("/generate/mcq/{video_id}", response_model=McqGenerateResponse)
def generate_mcq_quiz(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> McqGenerateResponse:
    """
    Generate 10 MCQs from the video's summary + transcript (OpenAI gpt-4o-mini).

    Replaces any previously stored MCQs for this video. Requires completed transcript and summary.
    """

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    ensure_quiz_regeneration_allowed(db, user=current_user, video_id=video_id)
    rows = generate_mcqs_for_video(db, video_id=video_id)
    return McqGenerateResponse(video_id=video_id, items=[_mcq_out(r) for r in rows])


@router.get("/mcq/{video_id}", response_model=McqListResponse)
def list_mcq_quiz(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> McqListResponse:
    """Return all MCQs by video_id (no ownership filtering)."""

    rows = db.scalars(select(Mcq).where(Mcq.video_id == video_id).order_by(Mcq.id.asc())).all()
    logger.info("MCQ fetch", extra={"video_id": video_id, "mcq_count": len(rows)})
    return McqListResponse(video_id=video_id, items=[_mcq_out(r) for r in rows])


@router.get("/mcq/video/{video_id}", response_model=McqListResponse)
def list_mcq_quiz_by_video_path(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> McqListResponse:
    """Public-style path variant for frontend usage; JWT required."""

    rows = db.scalars(select(Mcq).where(Mcq.video_id == video_id).order_by(Mcq.id.asc())).all()
    logger.info("MCQ fetch (video path)", extra={"video_id": video_id, "mcq_count": len(rows)})
    return McqListResponse(video_id=video_id, items=[_mcq_out(r) for r in rows])


# --- Short questions ---


@router.post("/generate/short/{video_id}", response_model=ShortQuestionGenerateResponse)
def generate_short_quiz(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShortQuestionGenerateResponse:
    """
    Generate 5 short questions with model answers (OpenAI gpt-4o-mini).

    Replaces any previously stored short questions for this video.
    """

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    rows = generate_short_questions_for_video(db, video_id=video_id)
    return ShortQuestionGenerateResponse(video_id=video_id, items=[_short_out(r) for r in rows])


@router.get("/short/{video_id}", response_model=ShortQuestionListResponse)
def list_short_quiz(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShortQuestionListResponse:
    """Return all short questions by video_id (no ownership filtering)."""

    rows = db.scalars(select(ShortQuestion).where(ShortQuestion.video_id == video_id).order_by(ShortQuestion.id.asc())).all()
    return ShortQuestionListResponse(video_id=video_id, items=[_short_out(r) for r in rows])


@router.get("/short/video/{video_id}", response_model=ShortQuestionListResponse)
def list_short_quiz_by_video_path(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShortQuestionListResponse:
    """Public-style path variant for frontend usage; JWT required."""

    rows = db.scalars(select(ShortQuestion).where(ShortQuestion.video_id == video_id).order_by(ShortQuestion.id.asc())).all()
    return ShortQuestionListResponse(video_id=video_id, items=[_short_out(r) for r in rows])


# --- Flashcards ---


@router.post("/generate/flashcards/{video_id}", response_model=FlashcardGenerateResponse)
def generate_flashcard_deck(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlashcardGenerateResponse:
    """
    Generate 10 flashcards from summary + transcript (OpenAI gpt-4o-mini).

    Replaces any previously stored flashcards for this video.
    """

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    rows = generate_flashcards_for_video(db, video_id=video_id)
    return FlashcardGenerateResponse(video_id=video_id, items=[_flash_out(r) for r in rows])


@router.get("/flashcards/{video_id}", response_model=FlashcardListResponse)
def list_flashcard_deck(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlashcardListResponse:
    """Return all flashcards by video_id (no ownership filtering)."""

    rows = db.scalars(select(Flashcard).where(Flashcard.video_id == video_id).order_by(Flashcard.id.asc())).all()
    return FlashcardListResponse(video_id=video_id, items=[_flash_out(r) for r in rows])


@router.get("/flashcards/video/{video_id}", response_model=FlashcardListResponse)
def list_flashcard_deck_by_video_path(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlashcardListResponse:
    """Public-style path variant for frontend usage; JWT required."""

    rows = db.scalars(select(Flashcard).where(Flashcard.video_id == video_id).order_by(Flashcard.id.asc())).all()
    update_progress(
        db,
        user_id=current_user.id,
        video_id=video_id,
        payload=ProgressUpdateIn(flashcards_viewed=True),
    )
    return FlashcardListResponse(video_id=video_id, items=[_flash_out(r) for r in rows])
