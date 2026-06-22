from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import MCQAttempt, ShortQuestionAttempt
from app.models.progress import VideoProgress
from app.models.quiz import Flashcard, Mcq
from app.models.summary import Summary, SummaryStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.video import Video
from app.schemas.progress_dashboard import (
    FlashcardResultOut,
    McqAttemptsOut,
    McqAttemptDetailOut,
    ShortQuestionAttemptsOut,
    ShortAttemptDetailOut,
    SummaryResultOut,
    TranscriptResultOut,
    VideoProgressOut,
    VideoResultsOut,
)
from app.schemas.videos import VideoOut
from app.services.progress_service import serialize_progress


def _mcq_option_text(mcq: Mcq, letter: str) -> str | None:
    answer = (letter or "").strip().upper()
    if answer == "A":
        return mcq.option_a
    if answer == "B":
        return mcq.option_b
    if answer == "C":
        return mcq.option_c
    if answer == "D":
        return mcq.option_d
    return None


def _video_out(v: Video) -> VideoOut:
    return VideoOut(
        id=v.id,
        title=v.title,
        filename=v.filename,
        file_path=v.file_path,
        uploaded_by=v.uploaded_by,
        file_size=v.file_size,
        duration=v.duration,
        status=v.status,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _progress_to_out(row: VideoProgress | None) -> VideoProgressOut | None:
    if row is None:
        return None
    return serialize_progress(row)


def get_video_results(db: Session, *, user_id: int, video_id: int) -> VideoResultsOut:
    """
    Full snapshot for one video: media metadata, pipeline outputs, attempts, flashcards, progress.
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
    transcript_out = TranscriptResultOut(
        status=transcript.status if transcript else "missing",
        language_detected=transcript.language_detected if transcript else None,
        transcript_text=(transcript.transcript_text or "") if transcript else "",
    )

    summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
    if summary:
        summary_out = SummaryResultOut(
            id=summary.id,
            status=summary.status,
            summary_text=summary.summary_text or "",
            summary_type=summary.summary_type,
        )
    else:
        summary_out = SummaryResultOut(id=None, status="missing", summary_text="", summary_type=None)

    mcq_rows_all = db.scalars(
        select(MCQAttempt)
        .where(MCQAttempt.user_id == user_id, MCQAttempt.video_id == video_id)
        .order_by(MCQAttempt.id.asc()),
    ).all()
    latest_mcq_created_at = mcq_rows_all[-1].created_at if mcq_rows_all else None
    mcq_rows = [r for r in mcq_rows_all if latest_mcq_created_at is not None and r.created_at == latest_mcq_created_at]
    mcq_ids = [r.question_id for r in mcq_rows]
    mcq_map: dict[int, Mcq] = {}
    if mcq_ids:
        mcq_map = {
            m.id: m
            for m in db.scalars(select(Mcq).where(Mcq.id.in_(mcq_ids))).all()
        }
    mcq_out = [
        McqAttemptDetailOut(
            id=r.id,
            question_id=r.question_id,
            question=(mcq_map[r.question_id].question if r.question_id in mcq_map else ""),
            selected_option=r.selected_option,
            is_correct=r.is_correct,
            score=r.score,
            correct_answer_letter=(mcq_map[r.question_id].correct_answer if r.question_id in mcq_map else None),
            correct_option_text=(
                _mcq_option_text(mcq_map[r.question_id], mcq_map[r.question_id].correct_answer)
                if r.question_id in mcq_map
                else None
            ),
            explanation=(mcq_map[r.question_id].explanation if r.question_id in mcq_map else None),
            created_at=r.created_at,
        )
        for r in mcq_rows
    ]
    mcq_total_correct = sum(1 for r in mcq_rows if r.is_correct)
    mcq_total_questions = len(mcq_rows)
    mcq_score_txt = f"{mcq_total_correct}/{mcq_total_questions}" if mcq_total_questions > 0 else None

    short_rows_all = db.scalars(
        select(ShortQuestionAttempt)
        .where(ShortQuestionAttempt.user_id == user_id, ShortQuestionAttempt.video_id == video_id)
        .order_by(ShortQuestionAttempt.id.asc()),
    ).all()
    latest_short_created_at = short_rows_all[-1].created_at if short_rows_all else None
    short_rows = [
        r for r in short_rows_all if latest_short_created_at is not None and r.created_at == latest_short_created_at
    ]
    short_out = [
        ShortAttemptDetailOut(
            id=r.id,
            question_id=r.question_id,
            student_answer=r.student_answer,
            score=r.score,
            max_score=5,
            feedback=r.feedback,
            created_at=r.created_at,
        )
        for r in short_rows
    ]
    short_total_score = sum(r.score for r in short_rows)
    short_max_total_score = 5 * len(short_rows)

    flash_rows = db.scalars(select(Flashcard).where(Flashcard.video_id == video_id).order_by(Flashcard.id.asc())).all()
    flash_out = [
        FlashcardResultOut(id=f.id, front=f.front, back=f.back, created_at=f.created_at) for f in flash_rows
    ]

    progress_row = db.scalar(
        select(VideoProgress).where(VideoProgress.user_id == user_id, VideoProgress.video_id == video_id),
    )

    return VideoResultsOut(
        video=_video_out(video),
        transcript=transcript_out,
        summary=summary_out,
        mcq_attempts=McqAttemptsOut(
            items=mcq_out,
            total_correct=mcq_total_correct,
            total_questions=mcq_total_questions,
            total_score_text=mcq_score_txt,
        ),
        short_question_attempts=ShortQuestionAttemptsOut(
            items=short_out,
            total_score=short_total_score,
            max_total_score=short_max_total_score,
        ),
        flashcards=flash_out,
        progress=_progress_to_out(progress_row),
    )
