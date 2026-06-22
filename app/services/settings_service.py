from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.assessment import MCQAttempt, ShortQuestionAttempt
from app.models.chat import ChatMessage, ChatSession
from app.models.progress import VideoProgress
from app.models.user import User
from app.models.video import Video
from app.services.avatar_service import remove_avatar_file
from app.services.video_service import delete_video


def update_user_full_name(db: Session, *, user: User, full_name: str) -> User:
    user.full_name = full_name
    db.commit()
    db.refresh(user)
    return user


def purge_user_account(db: Session, *, user_id: int) -> None:
    """
    Remove all LMS data for this user and delete the account.

    Owned videos use ``delete_video`` so media files are removed from disk.
    Remaining rows (progress, attempts, general chat) are cleared explicitly for SQLite FK reliability.
    """

    owned_video_ids = list(db.scalars(select(Video.id).where(Video.uploaded_by == user_id)).all())
    for vid in owned_video_ids:
        delete_video(db, user_id=user_id, video_id=vid)

    session_ids = select(ChatSession.id).where(ChatSession.user_id == user_id)
    db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
    db.execute(delete(ChatSession).where(ChatSession.user_id == user_id))
    db.execute(delete(VideoProgress).where(VideoProgress.user_id == user_id))
    db.execute(delete(MCQAttempt).where(MCQAttempt.user_id == user_id))
    db.execute(delete(ShortQuestionAttempt).where(ShortQuestionAttempt.user_id == user_id))

    user = db.get(User, user_id)
    if user is None:
        db.commit()
        return

    remove_avatar_file(user_id)

    db.delete(user)
    db.commit()
