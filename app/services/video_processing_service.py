from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audio import AudioStatus
from app.models.summary import Summary
from app.models.summary import SummaryStatus, SummaryType
from app.models.video import Video, VideoStatus
from app.models.transcript import TranscriptStatus
from app.services.audio_service import get_audio_for_video, request_audio_extraction
from app.services.audio_service import run_audio_extraction_background as run_audio_extraction
from app.services.quiz_generation_service import (
    generate_flashcards_for_video,
    generate_mcqs_for_video,
    generate_short_questions_for_video,
    list_flashcards_for_video,
    list_mcqs_for_video,
    list_short_questions_for_video,
)
from app.services.summarization_service import generate_summary
from app.services.transcript_service import generate_transcript, get_transcript_for_video


def _mark_step_result(
    steps: dict[str, dict[str, str | None]],
    *,
    step_name: str,
    status: str,
    detail: str | None = None,
) -> None:
    steps[step_name] = {"status": status, "detail": detail}
    print(f"Completed step: {step_name}")


def run_audio_then_transcript_background(*, video_id: int) -> None:
    """
    Background pipeline used by upload:
    1) extract audio
    2) generate transcript automatically when audio is done
    """

    run_audio_extraction(video_id=video_id)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        audio = get_audio_for_video(db, video_id=video_id)
        if audio is None or audio.status != AudioStatus.done.value:
            return
        generate_transcript(db, video_id=video_id)
    except Exception:
        # Best effort background chaining; audio endpoint remains resilient even if transcript fails.
        db.rollback()
    finally:
        db.close()


def run_full_processing_pipeline_background(*, video_id: int) -> None:
    """
    Background entrypoint that runs the full processing pipeline with its own DB session.
    """

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if video is None:
            return
        video.status = VideoStatus.processing.value
        db.commit()
        run_full_processing_pipeline(db, video_id=video_id)
        db.expire_all()
        video = db.get(Video, video_id)
        if video is not None:
            snapshot = get_processing_snapshot(db, video_id=video_id)
            video.transcript_status = str(snapshot["transcript_status"])
            video.summary_status = str(snapshot["summary_status"])
            if snapshot["overall_progress_percentage"] >= 100:
                video.status = VideoStatus.done.value
            else:
                video.status = VideoStatus.uploaded.value
            db.commit()
    except Exception:
        db.rollback()
        video = db.get(Video, video_id)
        if video is not None:
            video.status = VideoStatus.uploaded.value
            db.commit()
    finally:
        db.close()


def run_full_processing_pipeline(db: Session, *, video_id: int) -> dict[str, dict[str, str | None]]:
    """
    Run all processing steps in order and report each step status.
    """

    steps: dict[str, dict[str, str | None]] = {
        "audio_extraction": {"status": "pending", "detail": None},
        "transcription": {"status": "pending", "detail": None},
        "summary_generation": {"status": "pending", "detail": None},
        "mcq_generation": {"status": "pending", "detail": None},
        "short_questions_generation": {"status": "pending", "detail": None},
        "flashcard_generation": {"status": "pending", "detail": None},
    }

    # 1) Audio extraction
    print("Starting step: audio_extraction")
    try:
        audio = get_audio_for_video(db, video_id=video_id)
        if audio is not None and audio.status == AudioStatus.done.value:
            _mark_step_result(steps, step_name="audio_extraction", status="skipped", detail="Already completed.")
        else:
            request_audio_extraction(db, video_id=video_id)
            run_audio_extraction(video_id=video_id)
            db.expire_all()
            audio = get_audio_for_video(db, video_id=video_id)
            if audio is None or audio.status != AudioStatus.done.value:
                _mark_step_result(
                    steps,
                    step_name="audio_extraction",
                    status="failed",
                    detail="Audio extraction did not complete successfully.",
                )
            else:
                _mark_step_result(steps, step_name="audio_extraction", status="done")
    except TimeoutError:
        _mark_step_result(steps, step_name="audio_extraction", status="failed", detail="Audio extraction timed out.")
    except HTTPException as exc:
        _mark_step_result(steps, step_name="audio_extraction", status="failed", detail=str(exc.detail))
    except Exception:
        _mark_step_result(steps, step_name="audio_extraction", status="failed", detail="Audio extraction failed unexpectedly.")

    # 2) Transcript
    print("Starting step: transcription")
    try:
        transcript = get_transcript_for_video(db, video_id=video_id)
        if transcript is not None and transcript.status == TranscriptStatus.done.value:
            _mark_step_result(steps, step_name="transcription", status="skipped", detail="Already completed.")
        else:
            transcript = generate_transcript(db, video_id=video_id)
            if transcript.status != TranscriptStatus.done.value:
                _mark_step_result(steps, step_name="transcription", status="failed", detail="Transcript status is not done.")
            else:
                _mark_step_result(steps, step_name="transcription", status="done")
    except TimeoutError:
        _mark_step_result(steps, step_name="transcription", status="failed", detail="Transcription timed out.")
    except HTTPException as exc:
        _mark_step_result(steps, step_name="transcription", status="failed", detail=str(exc.detail))
    except Exception:
        _mark_step_result(steps, step_name="transcription", status="failed", detail="Transcription failed unexpectedly.")

    # 3) Summary
    print("Starting step: summary_generation")
    try:
        summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
        if summary is not None and summary.status == SummaryStatus.done.value:
            _mark_step_result(steps, step_name="summary_generation", status="skipped", detail="Already completed.")
        else:
            summary = generate_summary(db, video_id=video_id, summary_type=SummaryType.short.value)
            if summary.status != SummaryStatus.done.value:
                _mark_step_result(steps, step_name="summary_generation", status="failed", detail="Summary status is not done.")
            else:
                _mark_step_result(steps, step_name="summary_generation", status="done")
    except TimeoutError:
        _mark_step_result(steps, step_name="summary_generation", status="failed", detail="Summary generation timed out.")
    except HTTPException as exc:
        _mark_step_result(steps, step_name="summary_generation", status="failed", detail=str(exc.detail))
    except Exception:
        _mark_step_result(steps, step_name="summary_generation", status="failed", detail="Summary generation failed unexpectedly.")

    # 4) MCQs
    print("Starting step: mcq_generation")
    try:
        if len(list_mcqs_for_video(db, video_id=video_id)) > 0:
            _mark_step_result(steps, step_name="mcq_generation", status="skipped", detail="Already completed.")
        else:
            generate_mcqs_for_video(db, video_id=video_id)
            _mark_step_result(steps, step_name="mcq_generation", status="done")
    except TimeoutError:
        _mark_step_result(steps, step_name="mcq_generation", status="failed", detail="MCQ generation timed out.")
    except HTTPException as exc:
        _mark_step_result(steps, step_name="mcq_generation", status="failed", detail=str(exc.detail))
    except Exception:
        _mark_step_result(steps, step_name="mcq_generation", status="failed", detail="MCQ generation failed unexpectedly.")

    # 5) Short questions
    print("Starting step: short_questions_generation")
    try:
        if len(list_short_questions_for_video(db, video_id=video_id)) > 0:
            _mark_step_result(steps, step_name="short_questions_generation", status="skipped", detail="Already completed.")
        else:
            generate_short_questions_for_video(db, video_id=video_id)
            _mark_step_result(steps, step_name="short_questions_generation", status="done")
    except TimeoutError:
        _mark_step_result(
            steps,
            step_name="short_questions_generation",
            status="failed",
            detail="Short-question generation timed out.",
        )
    except HTTPException as exc:
        _mark_step_result(steps, step_name="short_questions_generation", status="failed", detail=str(exc.detail))
    except Exception:
        _mark_step_result(
            steps,
            step_name="short_questions_generation",
            status="failed",
            detail="Short-question generation failed unexpectedly.",
        )

    # 6) Flashcards
    print("Starting step: flashcard_generation")
    try:
        if len(list_flashcards_for_video(db, video_id=video_id)) > 0:
            _mark_step_result(steps, step_name="flashcard_generation", status="skipped", detail="Already completed.")
        else:
            generate_flashcards_for_video(db, video_id=video_id)
            _mark_step_result(steps, step_name="flashcard_generation", status="done")
    except TimeoutError:
        _mark_step_result(steps, step_name="flashcard_generation", status="failed", detail="Flashcard generation timed out.")
    except HTTPException as exc:
        _mark_step_result(steps, step_name="flashcard_generation", status="failed", detail=str(exc.detail))
    except Exception:
        _mark_step_result(steps, step_name="flashcard_generation", status="failed", detail="Flashcard generation failed unexpectedly.")

    return steps


def get_processing_snapshot(db: Session, *, video_id: int) -> dict[str, str | int]:
    audio = get_audio_for_video(db, video_id=video_id)
    transcript = get_transcript_for_video(db, video_id=video_id)
    mcq_count = len(list_mcqs_for_video(db, video_id=video_id))
    short_count = len(list_short_questions_for_video(db, video_id=video_id))
    flash_count = len(list_flashcards_for_video(db, video_id=video_id))

    from app.models.summary import Summary
    from sqlalchemy import select

    summary = db.scalar(select(Summary).where(Summary.video_id == video_id))

    summary_status = (summary.status if summary is not None else "pending")
    audio_done = audio is not None and audio.status == AudioStatus.done.value
    transcript_done = transcript is not None and transcript.status == TranscriptStatus.done.value
    summary_done = summary_status == SummaryStatus.done.value
    mcq_done = mcq_count > 0
    short_done = short_count > 0
    flash_done = flash_count > 0

    overall_progress_percentage = (
        (16 if audio_done else 0)
        + (17 if transcript_done else 0)
        + (17 if summary_done else 0)
        + (16 if mcq_done else 0)
        + (17 if short_done else 0)
        + (17 if flash_done else 0)
    )

    return {
        "audio_status": (audio.status if audio is not None else "pending"),
        "transcript_status": (transcript.status if transcript is not None else "pending"),
        "summary_status": summary_status,
        "mcq_count": mcq_count,
        "short_questions_count": short_count,
        "flashcards_count": flash_count,
        "overall_progress_percentage": overall_progress_percentage,
    }
