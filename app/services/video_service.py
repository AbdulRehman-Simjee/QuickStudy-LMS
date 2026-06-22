from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.assessment import MCQAttempt, ShortQuestionAttempt
from app.models.audio import Audio
from app.models.chat import ChatMessage, ChatSession
from app.models.progress import VideoProgress
from app.models.quiz import Flashcard, Mcq, ShortQuestion
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.models.video import Video, VideoStatus
from app.utils.files import ensure_dir, sanitize_filename


ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def _videos_dir() -> Path:
    settings = get_settings()
    return settings.uploads_dir / "videos"


def save_upload_to_disk(*, upload: UploadFile, max_bytes: int) -> tuple[str, str, int]:
    """
    Stream an UploadFile to disk, enforcing a maximum size.

    Returns: (stored_filename, file_path, file_size_bytes)
    """

    original = sanitize_filename(upload.filename or "video")
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    ensure_dir(_videos_dir())

    stored_filename = f"{uuid.uuid4().hex}{ext}"
    destination = _videos_dir() / stored_filename

    size = 0
    try:
        with destination.open("wb") as f:
            while True:
                chunk = upload.file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large. Max allowed is {max_bytes} bytes.",
                    )
                f.write(chunk)
    except Exception:
        # Best-effort cleanup on any failure
        if destination.exists():
            try:
                destination.unlink()
            except OSError:
                pass
        raise

    # store relative path string (portable)
    rel_path = str(destination.as_posix())
    return stored_filename, rel_path, size


def create_video_record(
    db: Session,
    *,
    title: str,
    stored_filename: str,
    file_path: str,
    file_size: int,
    uploaded_by: int,
    duration: float | None = None,
    youtube_url: str | None = None,
    status: str | None = None,
    transcript_status: str = "pending",
    summary_status: str = "pending",
) -> Video:
    video = Video(
        title=title,
        filename=stored_filename,
        file_path=file_path,
        uploaded_by=uploaded_by,
        file_size=file_size,
        duration=duration,
        status=status or VideoStatus.uploaded.value,
        youtube_url=youtube_url,
        transcript_status=transcript_status,
        summary_status=summary_status,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def list_user_videos(db: Session, *, user_id: int) -> list[Video]:
    return list(db.scalars(select(Video).where(Video.uploaded_by == user_id).order_by(Video.created_at.desc())))


def get_user_video(db: Session, *, user_id: int, video_id: int) -> Video | None:
    return db.scalar(select(Video).where(Video.id == video_id, Video.uploaded_by == user_id))


def rename_video_title(db: Session, *, user_id: int, video_id: int, new_title: str) -> Video:
    video = get_user_video(db, user_id=user_id, video_id=video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    video.title = new_title.strip()
    db.commit()
    db.refresh(video)
    return video


def delete_video(db: Session, *, user_id: int, video_id: int) -> int:
    video = get_user_video(db, user_id=user_id, video_id=video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    # Collect file paths first so we can remove blobs from disk before deleting DB rows.
    audio_rows = db.scalars(select(Audio).where(Audio.video_id == video_id)).all()
    audio_paths = [a.file_path for a in audio_rows if a.file_path]

    # Delete physical files first to avoid storage leaks.
    try:
        video_path = Path(video.file_path)
        if video_path.exists():
            video_path.unlink()
        for p in audio_paths:
            audio_path = Path(p)
            if audio_path.exists():
                audio_path.unlink()
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete media files from disk",
        )

    # Explicitly clear all related rows (important for SQLite setups without FK pragma enforcement).
    db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(select(ChatSession.id).where(ChatSession.video_id == video_id))))
    db.execute(delete(ChatSession).where(ChatSession.video_id == video_id))
    db.execute(delete(MCQAttempt).where(MCQAttempt.video_id == video_id))
    db.execute(delete(ShortQuestionAttempt).where(ShortQuestionAttempt.video_id == video_id))
    db.execute(delete(VideoProgress).where(VideoProgress.video_id == video_id))
    db.execute(delete(Flashcard).where(Flashcard.video_id == video_id))
    db.execute(delete(Mcq).where(Mcq.video_id == video_id))
    db.execute(delete(ShortQuestion).where(ShortQuestion.video_id == video_id))
    db.execute(delete(Summary).where(Summary.video_id == video_id))
    db.execute(delete(Transcript).where(Transcript.video_id == video_id))
    db.execute(delete(Audio).where(Audio.video_id == video_id))
    db.delete(video)
    db.commit()
    return video_id

