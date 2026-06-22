from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.datetime_support import UtcCreatedAtMixin


class McqOut(UtcCreatedAtMixin):
    id: int
    video_id: int
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    explanation: str
    created_at: datetime


class ShortQuestionOut(UtcCreatedAtMixin):
    id: int
    video_id: int
    question: str
    model_answer: str
    created_at: datetime


class FlashcardOut(UtcCreatedAtMixin):
    id: int
    video_id: int
    front: str
    back: str
    created_at: datetime


class McqListResponse(BaseModel):
    """All MCQs stored for a lecture video."""

    video_id: int
    items: list[McqOut] = Field(default_factory=list)


class ShortQuestionListResponse(BaseModel):
    video_id: int
    items: list[ShortQuestionOut] = Field(default_factory=list)


class FlashcardListResponse(BaseModel):
    video_id: int
    items: list[FlashcardOut] = Field(default_factory=list)


class McqGenerateResponse(BaseModel):
    message: str = Field(default="MCQs generated and saved")
    video_id: int
    items: list[McqOut]


class ShortQuestionGenerateResponse(BaseModel):
    message: str = Field(default="Short questions generated and saved")
    video_id: int
    items: list[ShortQuestionOut]


class FlashcardGenerateResponse(BaseModel):
    message: str = Field(default="Flashcards generated and saved")
    video_id: int
    items: list[FlashcardOut]
