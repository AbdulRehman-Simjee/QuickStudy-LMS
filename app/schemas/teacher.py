from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TeacherStudentSummaryOut(BaseModel):
    student_id: int
    name: str
    email: str
    videos_uploaded: int = 0
    quizzes_attempted: int = 0
    average_score: float = Field(default=0, ge=0, le=100)
    last_activity: datetime | None = None


class TeacherActivityOut(BaseModel):
    student_id: int
    student_name: str
    video_id: int
    video_title: str
    completion_percentage: int = Field(default=0, ge=0, le=100)
    last_activity: datetime | None = None


class TeacherDashboardOut(BaseModel):
    total_students: int
    total_videos_in_system: int
    total_summaries_generated: int
    total_quizzes_attempted: int
    average_class_score: float = Field(default=0, ge=0, le=100)
    students_list: list[TeacherStudentSummaryOut]
    recent_activity: list[TeacherActivityOut]


class TeacherStudentVideoProgressOut(BaseModel):
    video_id: int
    title: str
    completion_percentage: int = Field(default=0, ge=0, le=100)
    transcript_viewed: bool = False
    summary_viewed: bool = False
    mcq_attempted: bool = False
    short_questions_attempted: bool = False
    flashcards_viewed: bool = False
    chatbot_used: bool = False
    quizzes_attempted: int = 0
    average_score: float = Field(default=0, ge=0, le=100)
    last_activity: datetime | None = None


class TeacherStudentProgressOut(BaseModel):
    student_id: int
    name: str
    email: str
    videos_uploaded: int = 0
    quizzes_attempted: int = 0
    average_score: float = Field(default=0, ge=0, le=100)
    last_activity: datetime | None = None
    videos: list[TeacherStudentVideoProgressOut]
