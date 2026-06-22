from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audio import Audio, AudioStatus
from app.models.quiz import Flashcard, Mcq, ShortQuestion
from app.models.summary import Summary, SummaryStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.video import Video, VideoStatus
from app.services.audio_service import get_audio_for_video
from app.services.transcript_service import get_transcript_for_video


def find_youtube_processed_source(db: Session, *, url: str) -> Video | None:
    """Return any video with this YouTube URL that has completed transcript + summary processing."""

    return db.scalar(
        select(Video)
        .where(
            Video.youtube_url == url,
            Video.transcript_status == TranscriptStatus.done.value,
            Video.summary_status == SummaryStatus.done.value,
        )
        .order_by(Video.id.asc())
        .limit(1),
    )


def clone_youtube_processed_video(
    db: Session,
    *,
    source: Video,
    user_id: int,
    title: str,
    youtube_url: str,
) -> Video:
    """
    Create a new owned video row and copy processed assets (no download / API calls).
    Reuses the source media file path on disk.
    """

    new_video = Video(
        title=title,
        filename=source.filename,
        file_path=source.file_path,
        uploaded_by=user_id,
        file_size=source.file_size,
        duration=source.duration,
        status=VideoStatus.done.value,
        youtube_url=youtube_url,
        transcript_status=TranscriptStatus.done.value,
        summary_status=SummaryStatus.done.value,
    )
    db.add(new_video)
    db.flush()

    src_audio = get_audio_for_video(db, video_id=source.id)
    if src_audio is not None:
        new_audio = Audio(
            video_id=new_video.id,
            filename=src_audio.filename,
            file_path=src_audio.file_path,
            file_size=src_audio.file_size,
            duration=src_audio.duration,
            status=AudioStatus.done.value,
        )
        db.add(new_audio)
        db.flush()
    else:
        new_audio = Audio(
            video_id=new_video.id,
            filename="cached.mp3",
            file_path="",
            file_size=0,
            duration=None,
            status=AudioStatus.done.value,
        )
        db.add(new_audio)
        db.flush()

    src_transcript = get_transcript_for_video(db, video_id=source.id)
    if src_transcript is None:
        raise ValueError("Source video missing transcript for cache clone")
    new_transcript = Transcript(
        video_id=new_video.id,
        audio_id=new_audio.id,
        transcript_text=src_transcript.transcript_text,
        language_detected=src_transcript.language_detected,
        status=TranscriptStatus.done.value,
    )
    db.add(new_transcript)
    db.flush()

    src_summary = db.scalar(select(Summary).where(Summary.video_id == source.id))
    if src_summary is None:
        raise ValueError("Source video missing summary for cache clone")
    new_summary = Summary(
        video_id=new_video.id,
        transcript_id=new_transcript.id,
        summary_text=src_summary.summary_text,
        summary_type=src_summary.summary_type,
        status=SummaryStatus.done.value,
    )
    db.add(new_summary)

    for m in db.scalars(select(Mcq).where(Mcq.video_id == source.id)).all():
        db.add(
            Mcq(
                video_id=new_video.id,
                question=m.question,
                option_a=m.option_a,
                option_b=m.option_b,
                option_c=m.option_c,
                option_d=m.option_d,
                correct_answer=m.correct_answer,
                explanation=m.explanation,
            ),
        )

    for sq in db.scalars(select(ShortQuestion).where(ShortQuestion.video_id == source.id)).all():
        db.add(
            ShortQuestion(
                video_id=new_video.id,
                question=sq.question,
                model_answer=sq.model_answer,
            ),
        )

    for card in db.scalars(select(Flashcard).where(Flashcard.video_id == source.id)).all():
        db.add(
            Flashcard(
                video_id=new_video.id,
                front=card.front,
                back=card.back,
            ),
        )

    db.commit()
    db.refresh(new_video)
    return new_video
