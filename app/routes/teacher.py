from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_teacher
from app.models.user import User
from app.schemas.teacher import TeacherDashboardOut, TeacherStudentProgressOut, TeacherStudentSummaryOut
from app.services.teacher_service import build_teacher_dashboard, get_student_progress, list_students_progress

router = APIRouter(prefix="/teacher", tags=["Teacher"])


@router.get("/dashboard", response_model=TeacherDashboardOut)
def get_teacher_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_teacher),
) -> TeacherDashboardOut:
    """Teacher-level dashboard across students and system activity."""

    return build_teacher_dashboard(db)


@router.get("/students", response_model=list[TeacherStudentSummaryOut])
def get_teacher_students(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_teacher),
) -> list[TeacherStudentSummaryOut]:
    """List all students with aggregate progress."""

    return list_students_progress(db)


@router.get("/student/{student_id}/progress", response_model=TeacherStudentProgressOut)
def get_teacher_student_progress(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_teacher),
) -> TeacherStudentProgressOut:
    """Get full progress view for one student."""

    progress = get_student_progress(db, student_id=student_id)
    if progress is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return progress
