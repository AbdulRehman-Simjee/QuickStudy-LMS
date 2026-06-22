from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assessment import MCQAttempt, ShortQuestionAttempt
from app.models.progress import VideoProgress
from app.models.summary import Summary, SummaryStatus
from app.models.user import User, UserRole
from app.models.video import Video
from app.schemas.teacher import (
    TeacherActivityOut,
    TeacherDashboardOut,
    TeacherStudentProgressOut,
    TeacherStudentSummaryOut,
    TeacherStudentVideoProgressOut,
)
from app.services.dashboard_service import _latest_mcq_attempt_bundle, _short_percent_for_video

_SMART_OBE_EMAIL_SUFFIX = "%@smartobe.edu.pk"

def _collect_student_metrics(db: Session, *, student_id: int) -> tuple[int, int, float, datetime | None]:
    """Per learner: uploads, MCQ attempt rows, MCQ correctness %, latest activity across their progress rows."""

    videos_uploaded = int(
        db.scalar(select(func.count()).select_from(Video).where(Video.uploaded_by == student_id)) or 0,
    )
    quizzes_attempted = int(
        db.scalar(select(func.count()).select_from(MCQAttempt).where(MCQAttempt.user_id == student_id)) or 0,
    )

    average_score = 0.0
    if quizzes_attempted > 0:
        score_sum = db.scalar(
            select(func.coalesce(func.sum(MCQAttempt.score), 0)).where(MCQAttempt.user_id == student_id),
        )
        average_score = round(100.0 * float(score_sum or 0) / quizzes_attempted, 2)

    last_activity = db.scalar(
        select(func.max(VideoProgress.last_activity)).where(VideoProgress.user_id == student_id),
    )

    return videos_uploaded, quizzes_attempted, average_score, last_activity


def build_teacher_dashboard(db: Session) -> TeacherDashboardOut:
    total_students = int(
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == UserRole.student.value,
                User.email.like(_SMART_OBE_EMAIL_SUFFIX),
            ),
        )
        or 0,
    )
    total_videos_in_system = int(
        db.scalar(
            select(func.count())
            .select_from(Video)
            .join(User, Video.uploaded_by == User.id)
            .where(
                User.role == UserRole.student.value,
                User.email.like(_SMART_OBE_EMAIL_SUFFIX),
            ),
        )
        or 0,
    )
    total_summaries_generated = int(
        db.scalar(select(func.count()).select_from(Summary).where(Summary.status == SummaryStatus.done.value)) or 0,
    )
    total_quizzes_attempted = int(
        db.scalar(
            select(func.count())
            .select_from(MCQAttempt)
            .join(User, MCQAttempt.user_id == User.id)
            .where(
                User.role == UserRole.student.value,
                User.email.like(_SMART_OBE_EMAIL_SUFFIX),
            ),
        )
        or 0,
    )

    avg_class = 0.0
    if total_quizzes_attempted > 0:
        score_sum = db.scalar(
            select(func.coalesce(func.sum(MCQAttempt.score), 0))
            .select_from(MCQAttempt)
            .join(User, MCQAttempt.user_id == User.id)
            .where(
                User.role == UserRole.student.value,
                User.email.like(_SMART_OBE_EMAIL_SUFFIX),
            ),
        )
        avg_class = round(100.0 * float(score_sum or 0) / total_quizzes_attempted, 2)

    students = db.scalars(
        select(User)
        .where(
            User.role == UserRole.student.value,
            User.email.like(_SMART_OBE_EMAIL_SUFFIX),
        )
        .order_by(User.full_name.asc(), User.id.asc()),
    ).all()

    students_list: list[TeacherStudentSummaryOut] = []
    for student in students:
        videos_uploaded, quizzes_attempted, average_score, last_activity = _collect_student_metrics(
            db,
            student_id=student.id,
        )
        students_list.append(
            TeacherStudentSummaryOut(
                student_id=student.id,
                name=student.full_name,
                email=student.email,
                videos_uploaded=videos_uploaded,
                quizzes_attempted=quizzes_attempted,
                average_score=average_score,
                last_activity=last_activity,
            ),
        )

    progress_rows = db.scalars(
        select(VideoProgress)
        .join(User, VideoProgress.user_id == User.id)
        .where(User.role == UserRole.student.value)
        .where(User.email.like(_SMART_OBE_EMAIL_SUFFIX))
        .where(VideoProgress.last_activity.is_not(None))
        .order_by(VideoProgress.last_activity.desc())
        .limit(50),
    ).all()

    recent_activity: list[TeacherActivityOut] = []
    for row in progress_rows:
        video = db.get(Video, row.video_id)
        learner = db.get(User, row.user_id)
        if video is None or learner is None:
            continue
        recent_activity.append(
            TeacherActivityOut(
                student_id=learner.id,
                student_name=learner.full_name,
                video_id=video.id,
                video_title=video.title,
                completion_percentage=row.completion_percentage,
                last_activity=row.last_activity,
            ),
        )

    return TeacherDashboardOut(
        total_students=total_students,
        total_videos_in_system=total_videos_in_system,
        total_summaries_generated=total_summaries_generated,
        total_quizzes_attempted=total_quizzes_attempted,
        average_class_score=avg_class,
        students_list=students_list,
        recent_activity=recent_activity,
    )


def list_students_progress(db: Session) -> list[TeacherStudentSummaryOut]:
    students = db.scalars(
        select(User)
        .where(
            User.role == UserRole.student.value,
            User.email.like(_SMART_OBE_EMAIL_SUFFIX),
        )
        .order_by(User.full_name.asc(), User.id.asc()),
    ).all()
    out: list[TeacherStudentSummaryOut] = []
    for student in students:
        videos_uploaded, quizzes_attempted, average_score, last_activity = _collect_student_metrics(
            db,
            student_id=student.id,
        )
        out.append(
            TeacherStudentSummaryOut(
                student_id=student.id,
                name=student.full_name,
                email=student.email,
                videos_uploaded=videos_uploaded,
                quizzes_attempted=quizzes_attempted,
                average_score=average_score,
                last_activity=last_activity,
            ),
        )
    return out


def get_student_progress(db: Session, *, student_id: int) -> TeacherStudentProgressOut | None:
    student = db.get(User, student_id)
    if student is None or student.role != UserRole.student.value or not student.email.endswith("@smartobe.edu.pk"):
        return None

    videos = db.scalars(select(Video).where(Video.uploaded_by == student.id).order_by(Video.id.asc())).all()
    video_ids = [v.id for v in videos]
    progress_rows = (
        db.scalars(
            select(VideoProgress).where(
                VideoProgress.user_id == student.id,
                VideoProgress.video_id.in_(video_ids),
            ),
        ).all()
        if video_ids
        else []
    )
    progress_map = {row.video_id: row for row in progress_rows}

    videos_out: list[TeacherStudentVideoProgressOut] = []
    all_video_scores: list[float] = []

    for video in videos:
        mcq_rows = db.scalars(
            select(MCQAttempt).where(MCQAttempt.user_id == student.id, MCQAttempt.video_id == video.id),
        ).all()
        short_rows = db.scalars(
            select(ShortQuestionAttempt).where(
                ShortQuestionAttempt.user_id == student.id,
                ShortQuestionAttempt.video_id == video.id,
            ),
        ).all()
        progress = progress_map.get(video.id)

        quizzes_attempted_video = int(bool(mcq_rows) or bool(short_rows))
        score_parts: list[float] = []
        mcq_correct, mcq_q = _latest_mcq_attempt_bundle(db, user_id=student.id, video_id=video.id)
        if mcq_q > 0:
            score_parts.append(round(100.0 * mcq_correct / mcq_q, 2))
        short_pct = _short_percent_for_video(db, user_id=student.id, video_id=video.id)
        if short_pct is not None:
            score_parts.append(short_pct)
        average_score = round(sum(score_parts) / len(score_parts), 2) if score_parts else 0.0
        if score_parts:
            all_video_scores.append(average_score)

        videos_out.append(
            TeacherStudentVideoProgressOut(
                video_id=video.id,
                title=video.title,
                completion_percentage=(progress.completion_percentage if progress else 0),
                transcript_viewed=(progress.transcript_viewed if progress else False),
                summary_viewed=(progress.summary_viewed if progress else False),
                mcq_attempted=(progress.mcq_attempted if progress else False),
                short_questions_attempted=(progress.short_questions_attempted if progress else False),
                flashcards_viewed=(progress.flashcards_viewed if progress else False),
                chatbot_used=(progress.chatbot_used if progress else False),
                quizzes_attempted=quizzes_attempted_video,
                average_score=average_score,
                last_activity=(progress.last_activity if progress else None),
            ),
        )

    videos_uploaded, quizzes_attempted, _, last_activity = _collect_student_metrics(db, student_id=student.id)
    overall_average_score = round(sum(all_video_scores) / len(all_video_scores), 2) if all_video_scores else 0.0

    return TeacherStudentProgressOut(
        student_id=student.id,
        name=student.full_name,
        email=student.email,
        videos_uploaded=videos_uploaded,
        quizzes_attempted=quizzes_attempted,
        average_score=overall_average_score,
        last_activity=last_activity,
        videos=videos_out,
    )
