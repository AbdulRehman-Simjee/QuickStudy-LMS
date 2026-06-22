from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.datetime_support import (
    UtcCreatedAtMixin,
    UtcLastActivityOnlyMixin,
    UtcProgressTimestampsMixin,
)
from app.schemas.videos import VideoOut


# --- Progress ---


class ProgressUpdateIn(BaseModel):
    """
    Partial update: only fields explicitly sent are applied (set to True/False).
    Omit a field to leave it unchanged.
    """

    transcript_viewed: bool | None = None
    summary_viewed: bool | None = None
    mcq_attempted: bool | None = None
    short_questions_attempted: bool | None = None
    flashcards_viewed: bool | None = None
    chatbot_used: bool | None = None


class VideoProgressOut(UtcProgressTimestampsMixin):
    id: int | None = Field(default=None, description="Set once a progress row exists in the database.")
    user_id: int
    video_id: int
    transcript_viewed: bool
    summary_viewed: bool
    mcq_attempted: bool
    short_questions_attempted: bool
    flashcards_viewed: bool
    chatbot_used: bool
    completion_percentage: int = Field(..., ge=0, le=100)
    last_activity: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProgressUpdateResponse(BaseModel):
    message: str = Field(default="Progress updated")
    progress: VideoProgressOut


# --- Dashboard ---


class RecentVideoActivityOut(UtcLastActivityOnlyMixin):
    video_id: int
    title: str
    last_activity: datetime | None = Field(
        description="Latest progress touch, or video updated_at if no progress row exists.",
    )
    mcq_score: float = Field(default=0, description="Latest MCQ attempt score percentage for this video.")
    mcq_score_text: str | None = Field(default=None, description="Latest MCQ score text, e.g. 9/10.")
    quiz_attempted: bool = Field(default=False, description="True when at least one latest MCQ attempt exists.")
    completion_percentage: int = Field(default=0, ge=0, le=100)


class DashboardOut(BaseModel):
    total_videos_uploaded: int
    summaries_generated: int = Field(
        default=0,
        description="Total summaries generated for videos uploaded by this user.",
    )
    total_quizzes_attempted: int = Field(
        description="Distinct videos where the user has submitted at least one MCQ or short-answer assessment.",
    )
    average_mcq_score: float = Field(
        ...,
        description="Mean of per-video MCQ accuracy (latest attempt), as percentage 0–100.",
    )
    average_short_question_score: float = Field(
        ...,
        description="Mean of per-video short-answer totals as percentage of max, 0–100.",
    )
    recent_activity: list[RecentVideoActivityOut] = Field(
        default_factory=list,
        description="Up to five most recently active videos (by progress or video update).",
    )
    overall_progress_percentage: float = Field(
        ...,
        description="Mean completion_percentage across all uploaded videos (missing progress counts as 0).",
    )
    best_score: float = Field(
        ...,
        description="Best per-video MCQ accuracy (percentage) from latest attempts; 0 if none.",
    )
    total_chat_sessions: int
    study_hours_this_week: float = Field(
        default=0.0,
        description="Approximate hours of lecture video uploaded in the last 7 days (estimate, not session tracking).",
    )


# --- Results ---


class TranscriptResultOut(BaseModel):
    status: str
    language_detected: str | None
    transcript_text: str


class SummaryResultOut(BaseModel):
    id: int | None
    status: str
    summary_text: str
    summary_type: str | None


class McqAttemptDetailOut(UtcCreatedAtMixin):
    id: int
    question_id: int
    question: str
    selected_option: str
    is_correct: bool
    score: int
    correct_answer_letter: str | None = None
    correct_option_text: str | None = None
    explanation: str | None = None
    created_at: datetime


class ShortAttemptDetailOut(UtcCreatedAtMixin):
    id: int
    question_id: int
    student_answer: str
    score: int
    max_score: int = 5
    feedback: str
    created_at: datetime


class FlashcardResultOut(UtcCreatedAtMixin):
    id: int
    front: str
    back: str
    created_at: datetime


class McqAttemptsOut(BaseModel):
    items: list[McqAttemptDetailOut]
    total_correct: int
    total_questions: int
    total_score_text: str | None = None


class ShortQuestionAttemptsOut(BaseModel):
    items: list[ShortAttemptDetailOut]
    total_score: int
    max_total_score: int


class VideoResultsOut(BaseModel):
    video: VideoOut
    transcript: TranscriptResultOut
    summary: SummaryResultOut
    mcq_attempts: McqAttemptsOut
    short_question_attempts: ShortQuestionAttemptsOut
    flashcards: list[FlashcardResultOut]
    progress: VideoProgressOut | None = Field(
        default=None,
        description="Null if no progress row exists yet.",
    )
