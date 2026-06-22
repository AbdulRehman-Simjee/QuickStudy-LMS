"""
SQLAlchemy ORM models live here.

Tip: Import your model modules in `app/models/__init__.py` so metadata is registered
before migrations / table creation.
"""

from app.models.user import User, UserPlan, UserRole
from app.models.audio import Audio, AudioStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.video import Video, VideoStatus
from app.models.summary import Summary, SummaryStatus, SummaryType
from app.models.quiz import Flashcard, Mcq, ShortQuestion
from app.models.assessment import MCQAttempt, ShortQuestionAttempt
from app.models.chat import ChatMessage, ChatSession
from app.models.progress import VideoProgress

__all__ = [
    "User",
    "UserRole",
    "UserPlan",
    "Audio",
    "AudioStatus",
    "Transcript",
    "TranscriptStatus",
    "Summary",
    "SummaryStatus",
    "SummaryType",
    "Video",
    "VideoStatus",
    "Mcq",
    "ShortQuestion",
    "Flashcard",
    "MCQAttempt",
    "ShortQuestionAttempt",
    "ChatSession",
    "ChatMessage",
    "VideoProgress",
]

