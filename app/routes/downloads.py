from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.quiz import Flashcard, Mcq
from app.models.summary import Summary
from app.models.user import User
from app.models.video import Video
from app.services.plan_service import ensure_pdf_download_allowed
from app.services.pdf_service import build_flashcards_pdf, build_quiz_pdf, build_summary_pdf

router = APIRouter(prefix="/download", tags=["Downloads"])


def _require_owned_video(db: Session, *, video_id: int, user_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return video


@router.get("/summary-pdf/{video_id}")
def download_summary_pdf(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    ensure_pdf_download_allowed(current_user)
    video = _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
    if summary is None or not (summary.summary_text or "").strip():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")

    pdf_buffer = build_summary_pdf(video_title=video.title, summary_text=summary.summary_text)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="summary-video-{video_id}.pdf"'},
    )


@router.get("/flashcards-pdf/{video_id}")
def download_flashcards_pdf(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    ensure_pdf_download_allowed(current_user)
    video = _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    flashcards = db.scalars(select(Flashcard).where(Flashcard.video_id == video_id).order_by(Flashcard.id.asc())).all()
    if not flashcards:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flashcards not found")

    payload = [{"front": f.front, "back": f.back} for f in flashcards]
    pdf_buffer = build_flashcards_pdf(video_title=video.title, cards=payload)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="flashcards-video-{video_id}.pdf"'},
    )


@router.get("/quiz-pdf/{video_id}")
def download_quiz_pdf(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    ensure_pdf_download_allowed(current_user)
    video = _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    mcqs = db.scalars(select(Mcq).where(Mcq.video_id == video_id).order_by(Mcq.id.asc())).all()
    if not mcqs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCQs not found")

    payload = [
        {
            "question": q.question,
            "option_a": q.option_a,
            "option_b": q.option_b,
            "option_c": q.option_c,
            "option_d": q.option_d,
            "correct_answer": q.correct_answer,
        }
        for q in mcqs
    ]
    pdf_buffer = build_quiz_pdf(video_title=video.title, mcqs=payload)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="quiz-video-{video_id}.pdf"'},
    )
