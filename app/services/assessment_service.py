from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.assessment import MCQAttempt, ShortQuestionAttempt
from app.models.quiz import Mcq, ShortQuestion
from app.models.video import Video
from app.schemas.assessment import (
    McqResultItemOut,
    McqSubmitResponse,
    ShortResultItemOut,
    ShortSubmitResponse,
)
from app.services.text_refinement import MissingOpenAIKeyError, openai_chat_completion

logger = logging.getLogger(__name__)

MARKING_MODEL = "gpt-4o-mini"
_JSON_OBJECT_FORMAT = {"type": "json_object"}
_SHORT_MARK_SYSTEM = (
    "You are a fair, constructive examiner for QuickStudy LMS (higher education). "
    "For each item you receive: the question, the official model answer, and the student's answer. "
    "Score the student's answer from 0 to 5 (integers only): 5 = fully addresses key ideas; "
    "3–4 = partially correct; 1–2 = major gaps or misconceptions; 0 = irrelevant or empty substance. "
    "Write concise feedback (2–5 sentences): what was strong, what was missing or inaccurate, and how to improve. "
    "Be consistent and base judgments only on the question and model answer. "
    "Output a single JSON object only, no markdown."
)


class _ShortEvalItem(BaseModel):
    question_id: int
    score: int = Field(ge=0, le=5)
    feedback: str

    @field_validator("feedback")
    @classmethod
    def feedback_non_empty(cls, v: str) -> str:
        t = (v or "").strip()
        if not t:
            raise ValueError("feedback must be non-empty")
        return t


class _ShortEvalBatch(BaseModel):
    evaluations: list[_ShortEvalItem]


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Assessment JSON parse failed", extra={"snippet": text[:400]})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Marking service returned invalid JSON.",
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Marking service returned unexpected JSON shape.",
        )
    return data


def _mcq_option_text(mcq: Mcq, letter: str) -> str:
    m = {"A": mcq.option_a, "B": mcq.option_b, "C": mcq.option_c, "D": mcq.option_d}
    return m[letter.upper()].strip()


def submit_mcq_assessment(
    db: Session,
    *,
    user_id: int,
    video_id: int,
    answers: list[tuple[int, str]],
) -> McqSubmitResponse:
    """
    Grade MCQs for a video: allows partial submission, persists attempts, returns full  question breakdown.

    ``answers`` is a list of (question_id, selected_option) after request validation.
    """

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    mcqs = db.scalars(select(Mcq).where(Mcq.video_id == video_id).order_by(Mcq.id.asc())).all()
    if not mcqs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No MCQs exist for this video. Generate MCQs before submitting an assessment.",
        )

    expected_ids = {m.id for m in mcqs}
    submitted_map = {qid: opt.upper() for qid, opt in answers}
    if not set(submitted_map.keys()).issubset(expected_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Submitted answers include question IDs that do not belong to this video's MCQs.",
        )

    db.execute(delete(MCQAttempt).where(MCQAttempt.user_id == user_id, MCQAttempt.video_id == video_id))

    items_out: list[McqResultItemOut] = []
    total_correct = 0

    for mcq in mcqs:
        selected = submitted_map.get(mcq.id)
        correct_letter = mcq.correct_answer.strip().upper()
        is_ok = selected is not None and selected == correct_letter
        if is_ok:
            total_correct += 1
        row_score = 1 if is_ok else 0

        attempt = MCQAttempt(
            video_id=video_id,
            user_id=user_id,
            question_id=mcq.id,
            selected_option=(selected or "N/A"),
            is_correct=is_ok,
            score=row_score,
        )
        db.add(attempt)

        if is_ok:
            items_out.append(
                McqResultItemOut(
                    question_id=mcq.id,
                    selected_option=(selected or "N/A"),
                    is_correct=True,
                    correct_answer_letter=None,
                    correct_option_text=None,
                    explanation=mcq.explanation.strip(),
                )
            )
        else:
            items_out.append(
                McqResultItemOut(
                    question_id=mcq.id,
                    selected_option=(selected or "N/A"),
                    is_correct=False,
                    correct_answer_letter=correct_letter,
                    correct_option_text=_mcq_option_text(mcq, correct_letter),
                    explanation=mcq.explanation.strip(),
                )
            )

    db.commit()

    n = len(mcqs)
    logger.info(
        "MCQ assessment stored",
        extra={"video_id": video_id, "user_id": user_id, "total_correct": total_correct, "total": n},
    )
    return McqSubmitResponse(
        total_correct=total_correct,
        total_questions=n,
        total_score_text=f"{total_correct}/{n}",
        items=items_out,
    )


def submit_short_assessment(
    db: Session,
    *,
    user_id: int,
    video_id: int,
    answers: list[tuple[int, str]],
) -> ShortSubmitResponse:
    """
    AI-mark all short answers in one OpenAI call, persist attempts, return scores and feedback.
    """

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    questions = db.scalars(
        select(ShortQuestion).where(ShortQuestion.video_id == video_id).order_by(ShortQuestion.id.asc()),
    ).all()
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No short questions exist for this video. Generate them before submitting.",
        )

    expected_ids = {q.id for q in questions}
    answer_map = {qid: text.strip() for qid, text in answers}
    if set(answer_map.keys()) != expected_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Submit exactly one answer per short question; IDs must match all stored questions.",
        )

    blocks: list[str] = []
    for idx, sq in enumerate(questions, start=1):
        blocks.append(
            f"--- ITEM {idx} ---\n"
            f"question_id: {sq.id}\n"
            f"QUESTION:\n{sq.question.strip()}\n\n"
            f"MODEL_ANSWER:\n{sq.model_answer.strip()}\n\n"
            f"STUDENT_ANSWER:\n{answer_map[sq.id]}\n",
        )

    user_prompt = (
        "Evaluate each item below independently. Respond with JSON only:\n"
        '{"evaluations":[{"question_id":<int>,"score":<0-5 int>,"feedback":"<string>"}]}\n'
        f"Include exactly {len(questions)} objects in evaluations, one per item, with the question_id "
        "values exactly as given.\n\n"
        + "\n".join(blocks)
    )
    messages = [
        {"role": "system", "content": _SHORT_MARK_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = openai_chat_completion(
            messages=messages,
            max_tokens=8192,
            temperature=0.25,
            model=MARKING_MODEL,
            response_format=_JSON_OBJECT_FORMAT,
        )
    except MissingOpenAIKeyError as exc:
        logger.warning("Short-answer marking requires OpenAI API key", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required for AI marking. Set it in .env and restart the server.",
        ) from exc
    except Exception as exc:
        logger.exception("OpenAI short-answer marking failed", extra={"video_id": video_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI marking failed. Please try again.",
        ) from exc

    try:
        batch = _ShortEvalBatch.model_validate(_parse_json_object(raw))
    except ValidationError as exc:
        logger.warning("Short marking JSON validation failed", extra={"errors": exc.errors()})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI marking returned data in an invalid format. Try again.",
        ) from exc

    if len(batch.evaluations) != len(questions):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI marking returned the wrong number of evaluations.",
        )

    by_id = {e.question_id: e for e in batch.evaluations}
    if set(by_id.keys()) != expected_ids:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI marking returned mismatched question IDs.",
        )

    db.execute(
        delete(ShortQuestionAttempt).where(
            ShortQuestionAttempt.user_id == user_id,
            ShortQuestionAttempt.video_id == video_id,
        ),
    )

    items_out: list[ShortResultItemOut] = []
    total = 0
    max_per = 5

    for sq in questions:
        ev = by_id[sq.id]
        total += ev.score
        row = ShortQuestionAttempt(
            video_id=video_id,
            user_id=user_id,
            question_id=sq.id,
            student_answer=answer_map[sq.id],
            score=ev.score,
            feedback=ev.feedback,
        )
        db.add(row)
        items_out.append(
            ShortResultItemOut(
                question_id=sq.id,
                score=ev.score,
                max_score=max_per,
                feedback=ev.feedback,
            ),
        )

    db.commit()

    max_total = max_per * len(questions)
    logger.info(
        "Short assessment stored",
        extra={"video_id": video_id, "user_id": user_id, "total_score": total, "max": max_total},
    )
    return ShortSubmitResponse(
        items=items_out,
        total_score=total,
        max_total_score=max_total,
    )
