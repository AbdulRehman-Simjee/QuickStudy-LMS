from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.datetime_support import UtcCreatedUpdatedMixin


class VideoOut(UtcCreatedUpdatedMixin):
    id: int
    title: str
    filename: str
    file_path: str
    uploaded_by: int
    file_size: int
    duration: float | None
    status: str
    created_at: datetime
    updated_at: datetime


class VideoDetailOut(VideoOut):
    audio_status: str
    transcript_status: str
    summary_status: str
    mcq_count: int
    short_questions_count: int
    flashcards_count: int
    overall_progress_percentage: int


class VideoUploadResponse(BaseModel):
    message: str = Field(default="Upload successful")
    video: VideoOut


class YouTubeUploadRequest(BaseModel):
    url: str
    title: str | None = None


class VideoRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class VideoDeleteResponse(BaseModel):
    message: str = Field(default="Video deleted successfully")
    video_id: int


class VideoProcessStartResponse(BaseModel):
    status: str = Field(default="processing")
    message: str = Field(default="Processing started")

