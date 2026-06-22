from __future__ import annotations

import logging
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.quiz import Flashcard, Mcq
from app.models.summary import Summary, SummaryStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.video import Video
from app.services.text_refinement import MissingOpenAIKeyError, openai_chat_completion

logger = logging.getLogger(__name__)

CHAT_MODEL = "gpt-4o-mini"

# Bound primary lecture text (summary preferred; transcript excerpt only as fallback).
_CHAT_LECTURE_TEXT_MAX_CHARS = 12_000

# Cap stored turns sent back to the model (most recent first after slice = tail of list).
_MAX_HISTORY_MESSAGES = 48

_CHAT_ROLES: frozenset[str] = frozenset({"user", "assistant"})

_LECTURE_SYSTEM_PROMPT = (
    "You are QuickStudy AI Assistant, a helpful academic tutor. You have access to the lecture "
    "summary (or a transcript excerpt if no summary exists) plus optional MCQs and flashcards. "
    "Prioritize answering from that lecture context. For questions outside the lecture, "
    "use your general knowledge. Always be helpful, clear and academic in tone."
)

GENERAL_CHAT_SYSTEM_PROMPT = (
    "You are QuickStudy AI Assistant, a helpful academic tutor. Answer academic questions."
)


def _truncate(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n\n[… excerpt truncated …]"


def build_lecture_context_block(db: Session, *, video_id: int) -> str:
    """
    Assemble lecture text for chat: prefer **summary** (saves tokens); fall back to transcript excerpt.
    Append MCQs and flashcards when present.
    """

    parts: list[str] = []

    summary = db.scalar(select(Summary).where(Summary.video_id == video_id))
    summary_text = ""
    if summary and summary.status == SummaryStatus.done.value:
        summary_text = (summary.summary_text or "").strip()

    if summary_text:
        parts.append(
            "--- LECTURE SUMMARY ---\n"
            "Here is the lecture summary:\n"
            + _truncate(summary_text, _CHAT_LECTURE_TEXT_MAX_CHARS),
        )
    else:
        transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
        if transcript and transcript.status == TranscriptStatus.done.value and (transcript.transcript_text or "").strip():
            parts.append(
                "--- TRANSCRIPT (excerpt; summary unavailable) ---\n"
                + _truncate(transcript.transcript_text or "", _CHAT_LECTURE_TEXT_MAX_CHARS),
            )
        else:
            parts.append(
                "--- LECTURE SUMMARY ---\n"
                "(Not available or not yet generated.)",
            )

    mcqs = db.scalars(select(Mcq).where(Mcq.video_id == video_id).order_by(Mcq.id.asc())).all()
    if mcqs:
        lines: list[str] = ["--- MCQs (course-generated; use to clarify concepts and quiz prep) ---"]
        for i, m in enumerate(mcqs, start=1):
            lines.append(
                f"\n[MCQ {i}] {m.question.strip()}\n"
                f"  A) {m.option_a.strip()}\n  B) {m.option_b.strip()}\n  C) {m.option_c.strip()}\n"
                f"  D) {m.option_d.strip()}\n"
                f"  Correct: {m.correct_answer.strip().upper()} — {m.explanation.strip()}",
            )
        parts.append("\n".join(lines))
    else:
        parts.append("--- MCQs ---\n(None stored for this video.)")

    cards = db.scalars(select(Flashcard).where(Flashcard.video_id == video_id).order_by(Flashcard.id.asc())).all()
    if cards:
        clines = ["--- FLASHCARDS ---"]
        for i, c in enumerate(cards, start=1):
            clines.append(f"[{i}] Front: {c.front.strip()} | Back: {c.back.strip()}")
        parts.append("\n".join(clines))
    else:
        parts.append("--- FLASHCARDS ---\n(None stored for this video.)")

    return "\n\n".join(parts)


def _build_system_content(*, lecture_context: str) -> str:
    return (
        f"{_LECTURE_SYSTEM_PROMPT}\n\n"
        "--- LECTURE MATERIALS (summary-based when available; cite ideas from here when relevant) ---\n"
        f"{lecture_context}"
    )


def start_chat_session(db: Session, *, user_id: int, video_id: int) -> ChatSession:
    """Create a new chat session after verifying the video exists (caller enforces ownership)."""

    if db.get(Video, video_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    session = ChatSession(video_id=video_id, user_id=user_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("Chat session started", extra={"session_id": session.id, "video_id": video_id, "user_id": user_id})
    return session


def start_general_chat_session(db: Session, *, user_id: int) -> ChatSession:
    """Create a video-independent study chat session."""

    session = ChatSession(video_id=None, user_id=user_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("General chat session started", extra={"session_id": session.id, "user_id": user_id})
    return session


def _get_user_session(db: Session, *, session_id: int, user_id: int) -> ChatSession:
    session = db.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id),
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    return session


def _load_history_rows(db: Session, *, session_id: int) -> list[ChatMessage]:
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()),
    ).all()
    if any(r.role not in _CHAT_ROLES for r in rows):
        logger.error("Invalid chat message role in database", extra={"session_id": session_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat history is corrupted.",
        )
    return rows


def _openai_messages_for_turn(
    *,
    system_content: str,
    history: list[ChatMessage],
    new_user_text: str,
) -> list[dict[str, str]]:
    tail = history[-_MAX_HISTORY_MESSAGES:] if len(history) > _MAX_HISTORY_MESSAGES else history
    out: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    for m in tail:
        out.append({"role": m.role, "content": m.message})
    out.append({"role": "user", "content": new_user_text})
    return out


def send_chat_turn(
    db: Session,
    *,
    user_id: int,
    session_id: int,
    user_message: str,
) -> tuple[ChatMessage, ChatMessage]:
    """
    Persist the user's message, call OpenAI with system context + history, persist assistant reply.

    Returns the saved user and assistant ``ChatMessage`` rows (refreshed).
    """

    session = _get_user_session(db, session_id=session_id, user_id=user_id)
    text = user_message.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")

    if session.video_id is None:
        system_content = GENERAL_CHAT_SYSTEM_PROMPT
    else:
        lecture_context = build_lecture_context_block(db, video_id=session.video_id)
        system_content = _build_system_content(lecture_context=lecture_context)
    history = _load_history_rows(db, session_id=session_id)
    messages = _openai_messages_for_turn(system_content=system_content, history=history, new_user_text=text)

    try:
        reply = openai_chat_completion(
            messages=messages,
            max_tokens=4096,
            temperature=0.55,
            model=CHAT_MODEL,
            response_format=None,
        )
    except MissingOpenAIKeyError as exc:
        logger.warning("Chat requires OpenAI API key", extra={"session_id": session_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required for the assistant. Set it in .env and restart the server.",
        ) from exc
    except Exception as exc:
        logger.exception("Chat completion failed", extra={"session_id": session_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant could not respond. Please try again.",
        ) from exc

    reply = (reply or "").strip()
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant returned an empty response.",
        )

    user_row = ChatMessage(session_id=session_id, role="user", message=text)
    asst_row = ChatMessage(session_id=session_id, role="assistant", message=reply)
    db.add(user_row)
    db.add(asst_row)
    db.commit()
    db.refresh(user_row)
    db.refresh(asst_row)
    logger.debug("Chat turn stored", extra={"session_id": session_id, "user_id": user_id})
    return user_row, asst_row


def get_chat_history(db: Session, *, user_id: int, session_id: int) -> tuple[ChatSession, list[ChatMessage]]:
    session = _get_user_session(db, session_id=session_id, user_id=user_id)
    rows = _load_history_rows(db, session_id=session_id)
    return session, rows
