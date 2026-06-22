from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.summary import Summary, SummaryStatus, SummaryType
from app.models.transcript import Transcript, TranscriptStatus
from app.models.video import Video, VideoStatus
from app.services.text_refinement import (
    MissingOpenAIKeyError,
    clean_text_for_summarization,
    gpt_summarize_mixed_transcript,
    polish_academic_summary,
)

logger = get_logger(__name__)

# Transcripts longer than this (word count) use a detailed summary profile (longer output, higher max_tokens).
_SUMMARY_DETAILED_WORD_THRESHOLD = 1000


def generate_summary(
    db: Session,
    *,
    video_id: int,
    summary_type: str = SummaryType.short.value,
) -> Summary:
    """
    Build an English-only academic summary from the stored transcript.

    Uses OpenAI GPT (OPENAI_MODEL, default gpt-4o-mini) on the cleaned mixed-language transcript with
    chunking for long inputs, then polish_academic_summary (OpenAI when configured, else HF fallback).

    Summary length profile is chosen from transcript size: more than 1000 words uses ``detailed``;
    otherwise ``short``. The ``summary_type`` argument is ignored for this selection.
    """

    video = db.get(Video, video_id)
    if video is None or video.uploaded_by is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
    if transcript is None or transcript.status != TranscriptStatus.done.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transcript not ready yet. Generate transcript first and wait until status is done.",
        )

    transcript_text = clean_text_for_summarization(transcript.transcript_text or "")
    if not transcript_text.strip():
        summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
        if summary is not None:
            summary.status = SummaryStatus.failed.value
            db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transcript text is empty")

    word_count = len(transcript_text.split())
    if word_count > _SUMMARY_DETAILED_WORD_THRESHOLD:
        effective_summary_type = SummaryType.detailed.value
    else:
        effective_summary_type = SummaryType.short.value

    if summary_type != effective_summary_type:
        logger.debug(
            "Summary type derived from transcript word count",
            extra={
                "video_id": video_id,
                "caller_summary_type": summary_type,
                "effective_summary_type": effective_summary_type,
                "transcript_word_count": word_count,
            },
        )

    summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
    if summary is None:
        summary = Summary(
            video_id=video_id,
            transcript_id=transcript.id,
            summary_text="",
            summary_type=effective_summary_type,
            status=SummaryStatus.processing.value,
        )
        db.add(summary)
        db.commit()
        db.refresh(summary)
    else:
        summary.summary_type = effective_summary_type
        summary.transcript_id = transcript.id
        summary.status = SummaryStatus.processing.value
        summary.summary_text = ""
        db.commit()
        db.refresh(summary)

    try:
        logger.info("Summary generation started", extra={"video_id": video_id})

        summary_text = gpt_summarize_mixed_transcript(transcript=transcript_text, summary_type=effective_summary_type)
        if not summary_text.strip():
            raise RuntimeError("GPT summarization resulted in empty summary text")

        summary_text = polish_academic_summary(
            draft_summary=summary_text,
            lecture_context=transcript_text,
            summary_type=effective_summary_type,
        )

        summary.summary_text = summary_text.strip()
        summary.status = SummaryStatus.done.value
        if video is not None:
            video.summary_status = SummaryStatus.done.value
        db.commit()
        db.refresh(summary)
        logger.info("Summary completed", extra={"video_id": video_id})
        return summary
    except MissingOpenAIKeyError as exc:
        logger.error("Summary failed", extra={"video_id": video_id, "error": str(exc)})
        summary.status = SummaryStatus.failed.value
        if video is not None:
            video.summary_status = SummaryStatus.failed.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Summary generation requires OPENAI_API_KEY in the project root .env file. Restart the server after adding it.",
        ) from exc
    except RuntimeError as exc:
        logger.error("Summary failed", extra={"video_id": video_id, "error": str(exc)})
        summary.status = SummaryStatus.failed.value
        if video is not None:
            video.summary_status = SummaryStatus.failed.value
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Summary generation failed") from exc
    except Exception as exc:
        logger.error("Summary failed", extra={"video_id": video_id, "error": str(exc)})
        summary.status = SummaryStatus.failed.value
        if video is not None:
            video.summary_status = SummaryStatus.failed.value
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Summary generation failed") from exc
