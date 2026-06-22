from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException, status
try:
    # MoviePy v2+ exposes classes at package root
    from moviepy import VideoFileClip  # type: ignore
except Exception:  # pragma: no cover
    # Fallback for older MoviePy versions
    from moviepy.editor import VideoFileClip  # type: ignore
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.audio import Audio, AudioStatus
from app.models.video import Video, VideoStatus
from app.utils.files import ensure_dir


def _audio_dir() -> Path:
    settings = get_settings()
    return settings.uploads_dir / "audio"


def create_audio_record(db: Session, *, video_id: int, filename: str, file_path: str) -> Audio:
    audio = Audio(
        video_id=video_id,
        filename=filename,
        file_path=file_path,
        file_size=0,
        duration=None,
        status=AudioStatus.processing.value,
    )
    db.add(audio)
    db.commit()
    db.refresh(audio)
    return audio


def get_audio_for_video(db: Session, *, video_id: int) -> Audio | None:
    return db.scalar(select(Audio).where(Audio.video_id == video_id))


def _extract_audio_sync(*, video: Video, audio: Audio) -> None:
    """
    Synchronous extraction implementation (runs inside a background task).
    """

    ensure_dir(_audio_dir())

    out_filename = f"{uuid.uuid4().hex}.mp3"
    out_path = _audio_dir() / out_filename

    clip: VideoFileClip | None = None
    try:
        clip = VideoFileClip(video.file_path)
        if clip.audio is None:
            raise ValueError("No audio stream found in video")

        # MoviePy uses ffmpeg under the hood.
        clip.audio.write_audiofile(str(out_path), codec="mp3", logger=None)

        # Collect metadata
        size = out_path.stat().st_size
        duration = float(clip.duration) if clip.duration is not None else None

        # Persist results
        audio.filename = out_filename
        audio.file_path = out_path.as_posix()
        audio.file_size = size
        audio.duration = duration
        audio.status = AudioStatus.done.value

        video.status = VideoStatus.done.value
        if duration is not None:
            video.duration = duration
    except Exception:
        audio.status = AudioStatus.failed.value
        video.status = VideoStatus.uploaded.value
        # Best-effort cleanup of partial output
        try:
            if out_path.exists():
                out_path.unlink()
        except OSError:
            pass
        raise
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass


def run_audio_extraction_background(*, video_id: int) -> None:
    """
    Background task entrypoint.

    Creates its own DB session because FastAPI request-scoped sessions aren't
    safe to reuse outside the request lifecycle.
    """

    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if video is None:
            return

        audio = get_audio_for_video(db, video_id=video_id)
        if audio is None:
            # Shouldn't happen if called correctly, but keep it resilient.
            audio = create_audio_record(db, video_id=video_id, filename="pending.mp3", file_path="")

        # Mark processing
        video.status = VideoStatus.processing.value
        audio.status = AudioStatus.processing.value
        db.commit()

        _extract_audio_sync(video=video, audio=audio)
        db.commit()
    except Exception:
        db.rollback()
        # Ensure failure state is persisted if possible
        try:
            audio = get_audio_for_video(db, video_id=video_id)
            video = db.get(Video, video_id)
            if audio is not None:
                audio.status = AudioStatus.failed.value
            if video is not None:
                video.status = VideoStatus.uploaded.value
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def request_audio_extraction(db: Session, *, video_id: int) -> Audio:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    audio = get_audio_for_video(db, video_id=video_id)
    if audio is None:
        audio = create_audio_record(db, video_id=video_id, filename="pending.mp3", file_path="")
    else:
        # Allow re-run if previously failed; otherwise keep the existing record.
        if audio.status == AudioStatus.done.value:
            return audio
        audio.status = AudioStatus.processing.value
        db.commit()
        db.refresh(audio)

    video.status = VideoStatus.processing.value
    db.commit()
    return audio

