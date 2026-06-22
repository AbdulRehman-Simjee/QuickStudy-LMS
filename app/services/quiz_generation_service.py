from __future__ import annotations

import json
import random
import re
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.quiz import Flashcard, Mcq, ShortQuestion
from app.models.summary import Summary, SummaryStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.video import Video
from app.services.text_refinement import MissingOpenAIKeyError, openai_chat_completion

logger = get_logger(__name__)

# Quiz generation always uses this model per product spec (independent of optional OPENAI_MODEL overrides).
QUIZ_GENERATION_MODEL = "gpt-4o-mini"

# Cap transcript excerpt when falling back (summary is preferred and sent in full unless extremely large).
_QUIZ_TRANSCRIPT_MAX_CHARS = 14_000
_QUIZ_SUMMARY_MAX_CHARS = 24_000

_JSON_OBJECT_FORMAT = {"type": "json_object"}

_SYSTEM_MCQ = (
    "You are an expert instructional designer for QuickStudy LMS, an academic learning platform. "
    "Create clear, unambiguous multiple-choice questions that test understanding of the lecture material. "
    "Each question must have exactly four options in JSON fields option_a through option_d (these map to "
    "choices A, B, C, D in order). Only one option is correct; set correct_answer to that letter. "
    "Vary which option is correct across questions—do not default every question to option A. "
    "Across all 10 questions, spread correct_answer roughly evenly across A, B, C, and D (e.g. each letter "
    "about 2–3 times). "
    "Explanations should briefly justify the correct answer using ideas from the source. "
    "Do not refer to option letters (A, B, C, D) in the explanation—describe the correct concept or fact only, "
    "because option order may be rearranged after generation. "
    "Output must be a single JSON object only, no markdown fences."
)

_SYSTEM_SHORT = (
    "You are an expert educator for QuickStudy LMS. Write short open-ended questions that encourage recall "
    "and explanation of key ideas from the lecture. Provide a concise model answer (2–3 sentences) for each. "
    "Output must be a single JSON object only, no markdown fences."
)

_SYSTEM_FLASHCARDS = (
    "You are an expert educator for QuickStudy LMS. Create flashcards: front = key term or concept; "
    "back = clear definition or short explanation suitable for spaced repetition. "
    "Output must be a single JSON object only, no markdown fences."
)


class _McqItemPayload(BaseModel):
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    explanation: str

    @field_validator("correct_answer")
    @classmethod
    def normalize_answer(cls, v: str) -> str:
        letter = (v or "").strip().upper()
        if letter not in {"A", "B", "C", "D"}:
            raise ValueError("correct_answer must be A, B, C, or D")
        return letter


class _McqBatchPayload(BaseModel):
    mcqs: list[_McqItemPayload] = Field(min_length=10, max_length=10)


class _ShortItemPayload(BaseModel):
    question: str
    model_answer: str


class _ShortBatchPayload(BaseModel):
    short_questions: list[_ShortItemPayload] = Field(min_length=5, max_length=5)


class _FlashcardItemPayload(BaseModel):
    front: str
    back: str


class _FlashcardBatchPayload(BaseModel):
    flashcards: list[_FlashcardItemPayload] = Field(min_length=10, max_length=10)


_LETTER_TO_INDEX: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3}


def _balanced_correct_letter_schedule(*, n: int) -> list[str]:
    """
    Build a multiset of ``n`` letters A–D with counts as equal as possible, then shuffle.

    For n=10 this yields three letters appearing 3 times and one appearing 2 times (3+3+2+2),
    randomized in order so question index does not correlate with a fixed letter.
    """

    letters: list[str] = []
    for i in range(4):
        count = n // 4 + (1 if i < (n % 4) else 0)
        letters.extend([chr(ord("A") + i)] * count)
    random.shuffle(letters)
    return letters


def _remap_mcq_options_to_target_slot(
    *,
    option_a: str,
    option_b: str,
    option_c: str,
    option_d: str,
    correct_answer: str,
    target_letter: str,
) -> tuple[str, str, str, str, str]:
    """
    Place the semantically correct option at ``target_letter`` (A–D) and randomly permute distractors.

    Uses the model's ``correct_answer`` only to identify which of the four strings is correct; the stored
    ``correct_answer`` in the database becomes ``target_letter``. This removes positional bias from the LLM
    and enforces an even distribution of correct positions across the batch when paired with
    ``_balanced_correct_letter_schedule``.
    """

    opts = [option_a.strip(), option_b.strip(), option_c.strip(), option_d.strip()]
    idx = _LETTER_TO_INDEX[correct_answer.upper()]
    target_slot = _LETTER_TO_INDEX[target_letter.upper()]
    correct_text = opts[idx]
    wrong = [opts[j] for j in range(4) if j != idx]
    random.shuffle(wrong)

    placed: list[str] = [""] * 4
    placed[target_slot] = correct_text
    w = 0
    for slot in range(4):
        if slot == target_slot:
            continue
        placed[slot] = wrong[w]
        w += 1

    letter = chr(ord("A") + target_slot)
    return placed[0], placed[1], placed[2], placed[3], letter


def _truncate_transcript(text: str) -> str:
    t = (text or "").strip()
    if len(t) <= _QUIZ_TRANSCRIPT_MAX_CHARS:
        return t
    return t[:_QUIZ_TRANSCRIPT_MAX_CHARS] + "\n\n[… transcript truncated for quiz generation …]"


def _truncate_summary(text: str) -> str:
    t = (text or "").strip()
    if len(t) <= _QUIZ_SUMMARY_MAX_CHARS:
        return t
    return t[:_QUIZ_SUMMARY_MAX_CHARS] + "\n\n[… summary truncated for quiz generation …]"


def _build_quiz_context_block(*, used_summary: bool, context_text: str) -> str:
    """Single source block: summary when available, else transcript excerpt — avoids duplicate prompts and saves tokens."""

    ctx = context_text.strip()
    if used_summary:
        return (
            "Use ONLY the following lecture summary. Do not invent facts not supported by this material.\n\n"
            "--- LECTURE SUMMARY ---\n"
            f"{ctx}"
        )
    return (
        "Use ONLY the following lecture transcript excerpt (summary was unavailable). "
        "Do not invent facts not supported by this material.\n\n"
        "--- TRANSCRIPT EXCERPT ---\n"
        f"{ctx}"
    )


def _parse_json_object(raw: str) -> dict[str, Any]:
    """
    Parse model output as JSON. Strips optional ```json fences if the model adds them despite instructions.
    """

    text = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Quiz JSON parse failed", extra={"snippet": text[:500]})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Quiz generation returned invalid JSON. Try again.",
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Quiz generation returned unexpected JSON shape.",
        )
    return data


def _load_quiz_generation_context(db: Session, *, video_id: int) -> tuple[bool, str]:
    """
    Prefer completed summary text for quiz prompts; fall back to completed transcript excerpt.

    Returns (used_summary, context_text) for the user message block.
    """

    summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
    if summary is not None and summary.status == SummaryStatus.done.value:
        st = (summary.summary_text or "").strip()
        if st:
            return True, _truncate_summary(st)

    transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
    if transcript is not None and transcript.status == TranscriptStatus.done.value:
        tt = (transcript.transcript_text or "").strip()
        if tt:
            return False, _truncate_transcript(tt)

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Need a completed summary or transcript before generating quizzes. Generate processing pipeline first.",
    )


def generate_mcqs_for_video(db: Session, *, video_id: int) -> list[Mcq]:
    """
    Generate 10 MCQs via OpenAI, replace any existing MCQs for this video, persist and return rows.
    """

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    logger.info("MCQ generation started", extra={"video_id": video_id})
    used_summary, context_text = _load_quiz_generation_context(db, video_id=video_id)
    user_prompt = (
        _build_quiz_context_block(used_summary=used_summary, context_text=context_text)
        + "\n\nIMPORTANT: Vary the position of correct answer randomly across all options A, B, C, D. "
        "Do not always put correct answer as option A. "
        "Distribute correct answers evenly among A, B, C, D across all 10 questions "
        "(each letter should appear about 2–3 times as correct_answer).\n\n"
        "Respond with JSON matching this schema exactly:\n"
        '{"mcqs":[{"question":"...","option_a":"...","option_b":"...","option_c":"...","option_d":"...",'
        '"correct_answer":"A","explanation":"..."}]}\n'
        "Include exactly 10 objects in mcqs. correct_answer must be A, B, C, or D only."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_MCQ},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = openai_chat_completion(
            messages=messages,
            max_tokens=8192,
            temperature=0.35,
            model=QUIZ_GENERATION_MODEL,
            response_format=_JSON_OBJECT_FORMAT,
        )
    except MissingOpenAIKeyError as exc:
        logger.warning("MCQ generation requires OpenAI API key", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required for quiz generation. Set it in .env and restart the server.",
        ) from exc
    except Exception as exc:
        logger.exception("OpenAI MCQ generation failed", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate MCQs. Please try again.",
        ) from exc

    try:
        payload = _McqBatchPayload.model_validate(_parse_json_object(raw))
    except ValidationError as exc:
        logger.warning("MCQ JSON failed validation", extra={"video_id": video_id, "errors": exc.errors()})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Quiz generation produced invalid MCQ data. Try again.",
        ) from exc

    # Enforce balanced correct positions and random distractor order regardless of LLM positional bias.
    letter_schedule = _balanced_correct_letter_schedule(n=len(payload.mcqs))

    db.execute(delete(Mcq).where(Mcq.video_id == video_id))
    rows: list[Mcq] = []
    for item, target_letter in zip(payload.mcqs, letter_schedule, strict=True):
        oa, ob, oc, od, stored_letter = _remap_mcq_options_to_target_slot(
            option_a=item.option_a,
            option_b=item.option_b,
            option_c=item.option_c,
            option_d=item.option_d,
            correct_answer=item.correct_answer,
            target_letter=target_letter,
        )
        row = Mcq(
            video_id=video_id,
            question=item.question.strip(),
            option_a=oa,
            option_b=ob,
            option_c=oc,
            option_d=od,
            correct_answer=stored_letter,
            explanation=item.explanation.strip(),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for r in rows:
        db.refresh(r)
    logger.info("MCQ completed", extra={"video_id": video_id})
    return rows


def generate_short_questions_for_video(db: Session, *, video_id: int) -> list[ShortQuestion]:
    """Generate 5 short questions; replace existing rows for this video."""

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    logger.info("Short questions started", extra={"video_id": video_id})
    used_summary, context_text = _load_quiz_generation_context(db, video_id=video_id)
    user_prompt = (
        _build_quiz_context_block(used_summary=used_summary, context_text=context_text)
        + "\n\nRespond with JSON matching this schema exactly:\n"
        '{"short_questions":[{"question":"...","model_answer":"..."}]}\n'
        "Include exactly 5 objects. Each model_answer must be 2–3 sentences."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_SHORT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = openai_chat_completion(
            messages=messages,
            max_tokens=4096,
            temperature=0.4,
            model=QUIZ_GENERATION_MODEL,
            response_format=_JSON_OBJECT_FORMAT,
        )
    except MissingOpenAIKeyError as exc:
        logger.warning("Short-question generation requires OpenAI API key", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required for quiz generation. Set it in .env and restart the server.",
        ) from exc
    except Exception as exc:
        logger.exception("OpenAI short-question generation failed", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate short questions. Please try again.",
        ) from exc

    try:
        payload = _ShortBatchPayload.model_validate(_parse_json_object(raw))
    except ValidationError as exc:
        logger.warning("Short-question JSON failed validation", extra={"video_id": video_id, "errors": exc.errors()})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Quiz generation produced invalid short-question data. Try again.",
        ) from exc

    db.execute(delete(ShortQuestion).where(ShortQuestion.video_id == video_id))
    rows: list[ShortQuestion] = []
    for item in payload.short_questions:
        row = ShortQuestion(
            video_id=video_id,
            question=item.question.strip(),
            model_answer=item.model_answer.strip(),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for r in rows:
        db.refresh(r)
    logger.info("Short questions completed", extra={"video_id": video_id})
    return rows


def generate_flashcards_for_video(db: Session, *, video_id: int) -> list[Flashcard]:
    """Generate 10 flashcards; replace existing rows for this video."""

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    logger.info("Flashcards started", extra={"video_id": video_id})
    used_summary, context_text = _load_quiz_generation_context(db, video_id=video_id)
    user_prompt = (
        _build_quiz_context_block(used_summary=used_summary, context_text=context_text)
        + "\n\nRespond with JSON matching this schema exactly:\n"
        '{"flashcards":[{"front":"...","back":"..."}]}\n'
        "Include exactly 10 objects."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_FLASHCARDS},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = openai_chat_completion(
            messages=messages,
            max_tokens=6144,
            temperature=0.35,
            model=QUIZ_GENERATION_MODEL,
            response_format=_JSON_OBJECT_FORMAT,
        )
    except MissingOpenAIKeyError as exc:
        logger.warning("Flashcard generation requires OpenAI API key", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required for quiz generation. Set it in .env and restart the server.",
        ) from exc
    except Exception as exc:
        logger.exception("OpenAI flashcard generation failed", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate flashcards. Please try again.",
        ) from exc

    try:
        payload = _FlashcardBatchPayload.model_validate(_parse_json_object(raw))
    except ValidationError as exc:
        logger.warning("Flashcard JSON failed validation", extra={"video_id": video_id, "errors": exc.errors()})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Quiz generation produced invalid flashcard data. Try again.",
        ) from exc

    db.execute(delete(Flashcard).where(Flashcard.video_id == video_id))
    rows: list[Flashcard] = []
    for item in payload.flashcards:
        row = Flashcard(
            video_id=video_id,
            front=item.front.strip(),
            back=item.back.strip(),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for r in rows:
        db.refresh(r)
    logger.info("Flashcards completed", extra={"video_id": video_id})
    return rows


def list_mcqs_for_video(db: Session, *, video_id: int) -> list[Mcq]:
    return db.scalars(select(Mcq).where(Mcq.video_id == video_id).order_by(Mcq.id.asc())).all()


def list_short_questions_for_video(db: Session, *, video_id: int) -> list[ShortQuestion]:
    return db.scalars(select(ShortQuestion).where(ShortQuestion.video_id == video_id).order_by(ShortQuestion.id.asc())).all()


def list_flashcards_for_video(db: Session, *, video_id: int) -> list[Flashcard]:
    return db.scalars(select(Flashcard).where(Flashcard.video_id == video_id).order_by(Flashcard.id.asc())).all()
