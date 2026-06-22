from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.datetime_support import UtcCreatedAtMixin


class ChatSessionStartOut(UtcCreatedAtMixin):
    session_id: int
    video_id: int | None = None
    created_at: datetime


class GeneralChatSessionStartOut(UtcCreatedAtMixin):
    """Response for POST /chat/general/start (no lecture video)."""

    session_id: int
    created_at: datetime


class ChatSendMessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=12_000)


class ChatSendMessageOut(BaseModel):
    session_id: int
    user_message_id: int
    assistant_message_id: int
    response: str


class ChatHistoryMessageOut(UtcCreatedAtMixin):
    id: int
    role: str
    message: str
    created_at: datetime


class ChatHistoryOut(BaseModel):
    session_id: int
    video_id: int | None = None
    messages: list[ChatHistoryMessageOut]
