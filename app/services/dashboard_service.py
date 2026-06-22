from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assessment import MCQAttempt, ShortQuestionAttempt
from app.models.chat import ChatSession
from app.models.progress import VideoProgress
from app.models.summary import Summary
from app.models.video import Video
from app.schemas.progress_dashboard import DashboardOut, RecentVideoActivityOut

logger = logging.getLogger(__name__)


def _user_video_ids(db: Session, *, user_id: int) -> list[int]:
    return list(db.scalars(select(Video.id).where(Video.uploaded_by == user_id).order_by(Video.id.asc())).all())


def _mcq_percent_for_video(db: Session, *, user_id: int, video_id: int) -> float | None:
    rows = db.scalars(
        select(MCQAttempt).where(MCQAttempt.user_id == user_id, MCQAttempt.video_id == video_id),
    ).all()
    if not rows:
        return None
    total = sum(r.score for r in rows)
    return round(100.0 * total / len(rows), 2)


def _latest_mcq_attempt_bundle(db: Session, *, user_id: int, video_id: int) -> tuple[int, int]:
    """
    Return (total_correct, total_questions) for the latest MCQ attempt batch for this user+video.
    """

    rows = db.scalars(
        select(MCQAttempt)
        .where(MCQAttempt.user_id == user_id, MCQAttempt.video_id == video_id)
        .order_by(MCQAttempt.id.asc()),
    ).all()
    if not rows:
        return 0, 0
    latest_ts = rows[-1].created_at
    latest_rows = [r for r in rows if r.created_at == latest_ts]
    total_questions = len(latest_rows)
    total_correct = sum(1 for r in latest_rows if r.is_correct)
    return total_correct, total_questions


def _short_percent_for_video(db: Session, *, user_id: int, video_id: int) -> float | None:
    rows = db.scalars(
        select(ShortQuestionAttempt).where(
            ShortQuestionAttempt.user_id == user_id,
            ShortQuestionAttempt.video_id == video_id,
        ),
    ).all()
    if not rows:
        return None
    total_score = sum(r.score for r in rows)
    max_score = 5 * len(rows)
    if max_score <= 0:
        return None
    return round(100.0 * total_score / max_score, 2)


def build_dashboard(db: Session, *, user_id: int) -> DashboardOut:
    """
    Aggregate LMS metrics for the authenticated user (video owner in this deployment).
    """

    video_ids = _user_video_ids(db, user_id=user_id)
    total_videos = len(video_ids)

    vids_mcq = set(db.scalars(select(MCQAttempt.video_id).where(MCQAttempt.user_id == user_id)).all())
    vids_short = set(db.scalars(select(ShortQuestionAttempt.video_id).where(ShortQuestionAttempt.user_id == user_id)).all())
    total_quizzes_attempted = len(vids_mcq | vids_short)

    mcq_pcts: list[float] = []
    short_pcts: list[float] = []
    best_mcq = 0.0

    for vid in video_ids:
        mp = _mcq_percent_for_video(db, user_id=user_id, video_id=vid)
        if mp is not None:
            mcq_pcts.append(mp)
            best_mcq = max(best_mcq, mp)
        sp = _short_percent_for_video(db, user_id=user_id, video_id=vid)
        if sp is not None:
            short_pcts.append(sp)

    avg_mcq = round(sum(mcq_pcts) / len(mcq_pcts), 2) if mcq_pcts else 0.0
    avg_short = round(sum(short_pcts) / len(short_pcts), 2) if short_pcts else 0.0

    progress_map = {r.video_id: r for r in db.scalars(select(VideoProgress).where(VideoProgress.user_id == user_id)).all()}
    overall = 0.0
    if total_videos > 0:
        s = sum((progress_map.get(vid).completion_percentage if progress_map.get(vid) else 0) for vid in video_ids)
        overall = round(s / total_videos, 2)

    videos = db.scalars(select(Video).where(Video.uploaded_by == user_id).order_by(Video.id.asc())).all()
    ranked: list[tuple[datetime, Video, VideoProgress | None]] = []
    for v in videos:
        p = progress_map.get(v.id)
        ts = p.last_activity if p and p.last_activity is not None else v.updated_at
        ranked.append((ts, v, p))
    ranked.sort(key=lambda x: x[0], reverse=True)
    recent = [
        RecentVideoActivityOut(
            video_id=v.id,
            title=v.title,
            last_activity=ts,
            mcq_score=(round(100.0 * c / q, 2) if q > 0 else 0),
            mcq_score_text=(f"{c}/{q}" if q > 0 else None),
            quiz_attempted=q > 0,
            completion_percentage=(p.completion_percentage if p is not None else 0),
        )
        for ts, v, p in ranked[:5]
        for (c, q) in [_latest_mcq_attempt_bundle(db, user_id=user_id, video_id=v.id)]
    ]

    chat_count = int(
        db.scalar(select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id)) or 0,
    )
    summaries_generated = (
        db.query(Summary)
        .join(Video, Summary.video_id == Video.id)
        .filter(Video.uploaded_by == user_id)
        .filter(Summary.status == "done")
        .count()
    )

    logger.debug("Dashboard built", extra={"user_id": user_id, "videos": total_videos})

    return DashboardOut(
        total_videos_uploaded=total_videos,
        summaries_generated=summaries_generated,
        total_quizzes_attempted=total_quizzes_attempted,
        average_mcq_score=avg_mcq,
        average_short_question_score=avg_short,
        recent_activity=recent,
        overall_progress_percentage=overall,
        best_score=best_mcq,
        total_chat_sessions=chat_count,
    )
