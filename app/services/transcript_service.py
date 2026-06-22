from __future__ import annotations

import string
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, status
from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logger import get_logger
from app.models.audio import Audio, AudioStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.video import Video
from app.services.text_refinement import (
    MissingOpenAIKeyError,
    clean_mixed_language_transcript,
    openai_clean_mixed_transcript,
)

logger = get_logger(__name__)
_WHISPER_MAX_ATTEMPTS = 2
_WHISPER_MAX_FILE_BYTES = 25 * 1024 * 1024
_WHISPER_CHUNK_SECONDS = 10 * 60

# Punctuation-only tokens are kept even when alignment probability is low (Whisper attaches them to words).
_EXTRA_PUNCT = "۔،؟؛…‧·・"


def _is_primarily_punctuation_token(s: str) -> bool:
    s = s.strip()
    if not s:
        return True
    punct = set(string.punctuation + _EXTRA_PUNCT)
    return all((c in punct or c.isspace()) for c in s)


def _transcript_text_from_whisper_result(result: dict, *, min_word_probability: float) -> str:
    """
    Prefer word-level alignment probabilities when word_timestamps were enabled; otherwise full decode text.
    """

    segments = result.get("segments") or []
    blocks: list[str] = []
    for seg in segments:
        words = seg.get("words")
        if words:
            buf: list[str] = []
            for w in words:
                prob_raw = w.get("probability")
                prob = float(prob_raw) if prob_raw is not None else 1.0
                raw = w.get("word") or ""
                st = raw.strip()
                if not st:
                    continue
                if prob >= min_word_probability or _is_primarily_punctuation_token(st):
                    buf.append(raw)
            joined = "".join(buf).strip()
            if joined:
                blocks.append(joined)
        else:
            t = (seg.get("text") or "").strip()
            if t:
                blocks.append(t)

    text = "\n\n".join(blocks).strip()
    if text:
        return text
    return (result.get("text") or "").strip()


def _require_openai_key_for_transcription() -> str:
    settings = get_settings()
    if settings.openai_api_key is None:
        raise MissingOpenAIKeyError(
            "OPENAI_API_KEY is not set. Add it to the project root .env file, then restart the server."
        )
    key = settings.openai_api_key.get_secret_value().strip()
    if not key:
        raise MissingOpenAIKeyError(
            "OPENAI_API_KEY is empty. Add it to the project root .env file, then restart the server."
        )
    return key


def _verbose_transcription_to_dict(api_result) -> dict:
    """Normalize OpenAI Whisper API verbose_json into a dict for downstream filtering."""
    if hasattr(api_result, "model_dump"):
        return api_result.model_dump(mode="python")
    if isinstance(api_result, dict):
        return api_result
    text = getattr(api_result, "text", "") or ""
    language = getattr(api_result, "language", None)
    segments = getattr(api_result, "segments", None)
    out: dict = {"text": text, "language": language}
    if segments:
        out["segments"] = []
        for seg in segments:
            if hasattr(seg, "model_dump"):
                out["segments"].append(seg.model_dump(mode="python"))
            elif isinstance(seg, dict):
                out["segments"].append(seg)
            else:
                out["segments"].append(
                    {
                        "text": getattr(seg, "text", ""),
                        "words": getattr(seg, "words", None),
                    }
                )
    return out


def _run_openai_whisper_api_with_retry(*, audio_path: str, video_id: int, whisper_model: str) -> dict:
    """
    Call OpenAI Whisper API with bounded retries and rich logging.
    """
    settings = get_settings()
    api_key = _require_openai_key_for_transcription()
    client = OpenAI(api_key=api_key)

    last_exc: Exception | None = None
    for attempt in range(1, _WHISPER_MAX_ATTEMPTS + 1):
        try:
            logger.info(
                "OpenAI Whisper API transcription attempt started",
                extra={
                    "video_id": video_id,
                    "attempt": attempt,
                    "max_attempts": _WHISPER_MAX_ATTEMPTS,
                    "audio_file_path": audio_path,
                    "whisper_api_model": whisper_model,
                },
            )
            with open(audio_path, "rb") as audio_file:
                api_result = client.audio.transcriptions.create(
                    model=whisper_model,
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
            return _verbose_transcription_to_dict(api_result)
        except (APIError, APITimeoutError, RateLimitError) as exc:
            last_exc = exc
            logger.exception(
                "OpenAI Whisper API transcription failed",
                extra={
                    "video_id": video_id,
                    "attempt": attempt,
                    "max_attempts": _WHISPER_MAX_ATTEMPTS,
                    "audio_file_path": audio_path,
                    "whisper_api_model": whisper_model,
                    "error": repr(exc),
                },
            )
            if attempt >= _WHISPER_MAX_ATTEMPTS:
                raise
        except Exception as exc:
            last_exc = exc
            logger.exception(
                "OpenAI Whisper API transcription failed",
                extra={
                    "video_id": video_id,
                    "attempt": attempt,
                    "max_attempts": _WHISPER_MAX_ATTEMPTS,
                    "audio_file_path": audio_path,
                    "whisper_api_model": whisper_model,
                    "error": repr(exc),
                },
            )
            if attempt >= _WHISPER_MAX_ATTEMPTS:
                raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Whisper API failed with unknown error state.")


def _transcribe_openai_with_auto_chunking(*, audio_path: Path, video_id: int, whisper_model: str) -> dict:
    """
    OpenAI Whisper API has a 25MB upload limit.
    If audio exceeds this limit, split into 10-minute chunks and merge transcript text.
    """

    file_size = audio_path.stat().st_size
    if file_size <= _WHISPER_MAX_FILE_BYTES:
        return _run_openai_whisper_api_with_retry(
            audio_path=str(audio_path),
            video_id=video_id,
            whisper_model=whisper_model,
        )

    try:
        # MoviePy v2+
        from moviepy import AudioFileClip  # type: ignore
    except Exception:  # pragma: no cover
        # Fallback for older MoviePy versions
        from moviepy.editor import AudioFileClip  # type: ignore

    settings = get_settings()
    chunk_dir = settings.uploads_dir / "audio" / "chunks" / f"tx_{video_id}_{uuid.uuid4().hex[:8]}"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    clip: AudioFileClip | None = None
    chunk_paths: list[Path] = []
    try:
        clip = AudioFileClip(str(audio_path))
        duration = float(clip.duration or 0)
        if duration <= 0:
            raise RuntimeError("Audio duration is invalid for chunking.")

        merged_text_parts: list[str] = []
        merged_segments: list[dict] = []
        detected_language: str | None = None

        start = 0.0
        chunk_index = 0
        while start < duration:
            end = min(start + _WHISPER_CHUNK_SECONDS, duration)
            chunk_index += 1
            chunk_path = chunk_dir / f"chunk_{chunk_index:03d}.mp3"

            fresh_clip = AudioFileClip(str(audio_path))
            try:
                if hasattr(fresh_clip, "subclipped"):
                    sub = fresh_clip.subclipped(start, end)
                else:
                    sub = fresh_clip.subclip(start, end)
                sub.write_audiofile(str(chunk_path), codec="mp3", logger=None)
                try:
                    sub.close()
                except Exception:
                    pass
            finally:
                try:
                    fresh_clip.close()
                except Exception:
                    pass
            chunk_paths.append(chunk_path)

            chunk_size = chunk_path.stat().st_size
            logger.info(
                "Audio chunk created",
                extra={
                    "video_id": video_id,
                    "chunk_index": chunk_index,
                    "chunk_path": str(chunk_path),
                    "chunk_size_bytes": chunk_size,
                    "start": start,
                    "end": end,
                },
            )

            chunk_result = _run_openai_whisper_api_with_retry(
                audio_path=str(chunk_path),
                video_id=video_id,
                whisper_model=whisper_model,
            )
            if detected_language is None:
                detected_language = chunk_result.get("language")

            chunk_text = (chunk_result.get("text") or "").strip()
            if chunk_text:
                merged_text_parts.append(chunk_text)

            for seg in chunk_result.get("segments") or []:
                # Offset segment timestamps by chunk start for coherent merged timeline.
                seg_copy = dict(seg)
                if isinstance(seg_copy.get("start"), (int, float)):
                    seg_copy["start"] = float(seg_copy["start"]) + start
                if isinstance(seg_copy.get("end"), (int, float)):
                    seg_copy["end"] = float(seg_copy["end"]) + start
                merged_segments.append(seg_copy)

            start = end

        merged_text = "\n\n".join(merged_text_parts).strip()
        return {
            "text": merged_text,
            "language": detected_language,
            "segments": merged_segments,
        }
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass
        for p in chunk_paths:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        try:
            if chunk_dir.exists():
                chunk_dir.rmdir()
        except OSError:
            pass


def get_transcript_for_video(db: Session, *, video_id: int) -> Transcript | None:
    return db.scalar(select(Transcript).where(Transcript.video_id == video_id))


def generate_transcript(db: Session, *, video_id: int) -> Transcript:
    """
    Generate (or re-generate) a transcript for a video's extracted audio.

    Uses OpenAI Whisper API, then filters output and deterministically de-hallucinates, then cleans with OpenAI
    (no translation: English stays English; Urdu/Hindi stays Roman script). Requires OPENAI_API_KEY.
    """

    audio: Audio | None = db.scalar(select(Audio).where(Audio.video_id == video_id))
    if audio is None or audio.status != AudioStatus.done.value or not audio.file_path:
        logger.warning(
            "Transcript requested but audio not ready",
            extra={
                "video_id": video_id,
                "has_audio": audio is not None,
                "audio_status": getattr(audio, "status", None),
                "audio_file_path": getattr(audio, "file_path", None),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audio is not ready yet. Extract audio first and wait until status is done.",
        )

    audio_path = Path(audio.file_path)
    if not audio_path.exists():
        logger.error(
            "Transcript requested but audio file path does not exist",
            extra={
                "video_id": video_id,
                "audio_id": audio.id,
                "audio_file_path": audio.file_path,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found on disk. Re-run audio extraction before transcription.",
        )

    transcript = get_transcript_for_video(db, video_id=video_id)
    if transcript is None:
        transcript = Transcript(
            video_id=video_id,
            audio_id=audio.id,
            transcript_text="",
            language_detected=None,
            status=TranscriptStatus.processing.value,
        )
        db.add(transcript)
        db.commit()
        db.refresh(transcript)
    else:
        if transcript.status == TranscriptStatus.done.value:
            return transcript
        transcript.status = TranscriptStatus.processing.value
        transcript.audio_id = audio.id
        db.commit()
        db.refresh(transcript)

    settings = get_settings()
    whisper_model = (settings.whisper_api_model or "whisper-1").strip() or "whisper-1"
    word_prob_min = float(settings.whisper_word_probability_min)

    logger.info("Transcription started", extra={"video_id": video_id})

    try:
        t0 = time.perf_counter()
        result = _transcribe_openai_with_auto_chunking(
            audio_path=audio_path,
            video_id=video_id,
            whisper_model=whisper_model,
        )
        elapsed = round(time.perf_counter() - t0, 2)
        language = result.get("language")
        logger.info(
            "Whisper API transcription pass finished",
            extra={
                "video_id": video_id,
                "seconds": elapsed,
                "whisper_api_model": whisper_model,
                "language_detected": language,
            },
        )

        raw_text = _transcript_text_from_whisper_result(result, min_word_probability=word_prob_min)

        logger.info(
            "Cleaning transcript (deterministic pass)",
            extra={"video_id": video_id, "raw_chars": len(raw_text)},
        )
        deterministic = clean_mixed_language_transcript(raw_text)

        logger.info(
            "OpenAI transcript cleaning (mixed language, no translation)",
            extra={"video_id": video_id, "chars": len(deterministic)},
        )
        text = openai_clean_mixed_transcript(transcript=deterministic)
        logger.info(
            "Transcript ready",
            extra={"video_id": video_id, "final_chars": len(text)},
        )

        transcript.transcript_text = text
        transcript.language_detected = language
        transcript.status = TranscriptStatus.done.value
        video_row = db.get(Video, video_id)
        if video_row is not None:
            video_row.transcript_status = TranscriptStatus.done.value
        db.commit()
        db.refresh(transcript)
        logger.info(
            "Transcription completed",
            extra={"video_id": video_id, "seconds": elapsed},
        )
        return transcript
    except MissingOpenAIKeyError as exc:
        logger.exception("Transcription failed", extra={"video_id": video_id, "error": str(exc)})
        transcript.status = TranscriptStatus.failed.value
        video_row = db.get(Video, video_id)
        if video_row is not None:
            video_row.transcript_status = TranscriptStatus.failed.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcript requires OPENAI_API_KEY in the project root .env file. Restart the server after adding it.",
        ) from exc
    except (APIError, APITimeoutError, RateLimitError) as exc:
        logger.exception(
            "Transcription failed",
            extra={"video_id": video_id, "error": repr(exc)},
        )
        transcript.status = TranscriptStatus.failed.value
        video_row = db.get(Video, video_id)
        if video_row is not None:
            video_row.transcript_status = TranscriptStatus.failed.value
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Whisper transcription service failed. Please try again later.",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Transcription failed",
            extra={"video_id": video_id, "error": repr(exc)},
        )
        transcript.status = TranscriptStatus.failed.value
        video_row = db.get(Video, video_id)
        if video_row is not None:
            video_row.transcript_status = TranscriptStatus.failed.value
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transcription failed")
