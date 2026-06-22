from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logger import get_logger
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.video import Video
from app.models.user import User
from app.services.plan_service import ensure_video_upload_allowed
from app.schemas.videos import (
    VideoDeleteResponse,
    VideoDetailOut,
    VideoOut,
    VideoProcessStartResponse,
    VideoRenameRequest,
    YouTubeUploadRequest,
    VideoUploadResponse,
)
from app.services.video_processing_service import (
    get_processing_snapshot,
    run_full_processing_pipeline_background,
)
from app.services.video_service import (
    create_video_record,
    delete_video,
    get_user_video,
    list_user_videos,
    rename_video_title,
    save_upload_to_disk,
)
from app.services.youtube_cache_service import clone_youtube_processed_video, find_youtube_processed_source
from app.services.youtube_service import download_youtube_video, is_supported_youtube_url

logger = get_logger(__name__)

router = APIRouter(prefix="/videos", tags=["Videos"])


def _to_video_out(v) -> VideoOut:
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


def _probe_duration_seconds(file_path: str) -> float | None:
    try:
        from moviepy import VideoFileClip  # type: ignore
    except Exception:  # pragma: no cover
        from moviepy.editor import VideoFileClip  # type: ignore

    clip = None
    try:
        clip = VideoFileClip(file_path)
        if clip.duration is None:
            return None
        return float(clip.duration)
    except Exception:
        return None
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass


@router.post("/upload", response_model=VideoUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_video(
    title: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoUploadResponse:
    """
    Upload a video file and store metadata in the database.
    """

    logger.info(
        "Video upload started",
        extra={"title": title.strip(), "user_id": current_user.id},
    )
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    try:
        stored_filename, file_path, file_size = save_upload_to_disk(upload=file, max_bytes=max_bytes)
        duration_seconds = _probe_duration_seconds(file_path)
        try:
            ensure_video_upload_allowed(db, user=current_user, duration_seconds=duration_seconds)
        except HTTPException:
            p = Path(file_path)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
            raise

        video = create_video_record(
            db,
            title=title.strip(),
            stored_filename=stored_filename,
            file_path=file_path,
            file_size=file_size,
            uploaded_by=current_user.id,
            duration=duration_seconds,
        )
        return VideoUploadResponse(video=_to_video_out(video))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Upload failed", extra={"reason": str(exc), "user_id": current_user.id})
        raise


@router.post("/upload-youtube", response_model=VideoUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_youtube_video(
    payload: YouTubeUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoUploadResponse:
    """
    Download and upload a YouTube video by URL.
    """

    url = (payload.url or "").strip()
    if not is_supported_youtube_url(url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid YouTube URL")

    logger.info(
        "YouTube URL upload",
        extra={"url": url, "user_id": current_user.id},
    )

    final_title = (payload.title or "").strip()

    existing = find_youtube_processed_source(db, url=url)
    if existing is not None:
        logger.info("YouTube cache hit: %s", url)
        title = final_title or existing.title
        try:
            ensure_video_upload_allowed(db, user=current_user, duration_seconds=existing.duration)
        except HTTPException:
            raise
        video = clone_youtube_processed_video(
            db,
            source=existing,
            user_id=current_user.id,
            title=title,
            youtube_url=url,
        )
        return VideoUploadResponse(video=_to_video_out(video))

    logger.info("YouTube cache miss: %s", url)

    try:
        settings = get_settings()
        videos_dir = settings.uploads_dir / "videos"
        filename, file_path, yt_title, file_size = download_youtube_video(url=url, save_path=videos_dir)
        final_title = final_title or yt_title
        duration_seconds = _probe_duration_seconds(file_path)
        try:
            ensure_video_upload_allowed(db, user=current_user, duration_seconds=duration_seconds)
        except HTTPException:
            p = Path(file_path)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
            raise

        video = create_video_record(
            db,
            title=final_title,
            stored_filename=filename,
            file_path=file_path,
            file_size=file_size,
            uploaded_by=current_user.id,
            duration=duration_seconds,
            youtube_url=url,
        )
        return VideoUploadResponse(video=_to_video_out(video))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Upload failed", extra={"reason": str(exc), "url": url, "user_id": current_user.id})
        raise


@router.get("/", response_model=list[VideoOut])
def list_videos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VideoOut]:
    """
    List all videos uploaded by the current user.
    """

    videos = list_user_videos(db, user_id=current_user.id)
    return [_to_video_out(v) for v in videos]


@router.get("/{video_id}", response_model=VideoDetailOut)
def get_video(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoDetailOut:
    """
    Get a single video owned by the current user.
    """

    video = get_user_video(db, user_id=current_user.id, video_id=video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    processing = get_processing_snapshot(db, video_id=video_id)
    return VideoDetailOut(**_to_video_out(video).model_dump(), **processing)


@router.post("/process-all/{video_id}", response_model=VideoProcessStartResponse)
def process_all(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoProcessStartResponse:
    """
    Run the full processing sequence for a video (owner-only):
    audio extraction -> transcript -> summary -> MCQs -> short questions -> flashcards.
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    if video.status == "processing":
        return VideoProcessStartResponse(status="already_processing", message="Already processing")

    background_tasks.add_task(run_full_processing_pipeline_background, video_id=video_id)
    return VideoProcessStartResponse()


@router.patch("/{video_id}/rename", response_model=VideoDetailOut)
def rename_video(
    video_id: int,
    payload: VideoRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoDetailOut:
    """
    Rename a video title (owner-only).
    """

    updated = rename_video_title(db, user_id=current_user.id, video_id=video_id, new_title=payload.title)
    processing = get_processing_snapshot(db, video_id=video_id)
    return VideoDetailOut(**_to_video_out(updated).model_dump(), **processing)


@router.delete("/{video_id}", response_model=VideoDeleteResponse)
def delete_video_endpoint(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VideoDeleteResponse:
    """
    Delete an owned video (file + database record).
    """

    deleted_video_id = delete_video(db, user_id=current_user.id, video_id=video_id)
    return VideoDeleteResponse(video_id=deleted_video_id)

