from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.video import Video
from app.schemas.chat import (
    ChatHistoryMessageOut,
    ChatHistoryOut,
    ChatSendMessageIn,
    ChatSendMessageOut,
    ChatSessionStartOut,
    GeneralChatSessionStartOut,
)
from app.schemas.progress_dashboard import ProgressUpdateIn
from app.services.chat_service import (
    get_chat_history,
    send_chat_turn,
    start_chat_session,
    start_general_chat_session,
)
from app.services.plan_service import ensure_chat_limit_allowed
from app.services.progress_service import update_progress

router = APIRouter(prefix="/chat", tags=["Chat"])


def _require_owned_video(db: Session, *, video_id: int, user_id: int) -> None:
    video = db.get(Video, video_id)
    if video is None or video.uploaded_by != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")


@router.post("/start/{video_id}", response_model=ChatSessionStartOut)
def start_chat(
    video_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionStartOut:
    """
    Open a new assistant session for this video (owner-only).

    Lecture context (transcript, summary, MCQs, flashcards) is loaded on each message so it stays
    current; this endpoint only creates the session record and returns ``session_id``.
    """

    _require_owned_video(db, video_id=video_id, user_id=current_user.id)
    session = start_chat_session(db, user_id=current_user.id, video_id=video_id)
    update_progress(
        db,
        user_id=current_user.id,
        video_id=video_id,
        payload=ProgressUpdateIn(chatbot_used=True),
    )
    return ChatSessionStartOut(session_id=session.id, video_id=session.video_id, created_at=session.created_at)


@router.post("/general/start", response_model=GeneralChatSessionStartOut)
def start_general_chat(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GeneralChatSessionStartOut:
    """
    Open a new assistant session not tied to any lecture video.

    Any authenticated role may use this (students and teachers); there is no role gate here.
    """

    session = start_general_chat_session(db, user_id=current_user.id)
    return GeneralChatSessionStartOut(session_id=session.id, created_at=session.created_at)


@router.post("/message/{session_id}", response_model=ChatSendMessageOut)
def post_message(
    session_id: int,
    body: ChatSendMessageIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSendMessageOut:
    """
    Send a user message; the API appends prior turns from this session and returns the model reply.

    Uses OpenAI gpt-4o-mini with the lecture materials in the system prompt.
    """

    ensure_chat_limit_allowed(db, user=current_user)
    user_row, asst_row = send_chat_turn(
        db,
        user_id=current_user.id,
        session_id=session_id,
        user_message=body.message,
    )
    return ChatSendMessageOut(
        session_id=session_id,
        user_message_id=user_row.id,
        assistant_message_id=asst_row.id,
        response=asst_row.message,
    )


@router.get("/history/{session_id}", response_model=ChatHistoryOut)
def chat_history(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatHistoryOut:
    """Return all messages for this session in chronological order (owner-only)."""

    session, rows = get_chat_history(db, user_id=current_user.id, session_id=session_id)
    return ChatHistoryOut(
        session_id=session.id,
        video_id=session.video_id,
        messages=[
            ChatHistoryMessageOut(id=m.id, role=m.role, message=m.message, created_at=m.created_at) for m in rows
        ],
    )
