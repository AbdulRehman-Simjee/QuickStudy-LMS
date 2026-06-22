from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class McqAnswerSubmit(BaseModel):
    question_id: int = Field(..., ge=1)
    selected_option: str = Field(..., min_length=1, max_length=1)

    @field_validator("selected_option")
    @classmethod
    def option_letter(cls, v: str) -> str:
        letter = (v or "").strip().upper()
        if letter not in {"A", "B", "C", "D"}:
            raise ValueError("selected_option must be A, B, C, or D")
        return letter


class McqSubmitRequest(BaseModel):
    """One entry per MCQ for the video; IDs must match all stored questions exactly."""

    answers: list[McqAnswerSubmit] = Field(..., min_length=1)

    @model_validator(mode="after")
    def unique_question_ids(self):
        ids = [a.question_id for a in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("Each question_id must appear at most once")
        return self


class McqResultItemOut(BaseModel):
    question_id: int
    selected_option: str
    is_correct: bool
    correct_answer_letter: str | None = Field(
        default=None,
        description="When incorrect, the letter of the correct option; omitted when the student was correct.",
    )
    correct_option_text: str | None = Field(
        default=None,
        description="When incorrect, the full text of the correct option; omitted when the student was correct.",
    )
    explanation: str


class McqSubmitResponse(BaseModel):
    total_correct: int
    total_questions: int
    total_score_text: str = Field(..., description="Human-readable score, e.g. 7/10")
    items: list[McqResultItemOut]


class ShortAnswerSubmit(BaseModel):
    question_id: int = Field(..., ge=1)
    student_answer: str = Field(..., min_length=1, max_length=20_000)


class ShortSubmitRequest(BaseModel):
    answers: list[ShortAnswerSubmit] = Field(..., min_length=1)

    @model_validator(mode="after")
    def unique_question_ids(self):
        ids = [a.question_id for a in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("Each question_id must appear at most once")
        return self


class ShortResultItemOut(BaseModel):
    question_id: int
    score: int = Field(..., ge=0, le=5)
    max_score: int = Field(default=5)
    feedback: str


class ShortSubmitResponse(BaseModel):
    items: list[ShortResultItemOut]
    total_score: int
    max_total_score: int
