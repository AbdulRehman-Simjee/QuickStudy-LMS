from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.quiz import Mcq
from app.models.user import User, UserPlan, UserRole
from app.models.video import Video
from app.schemas.billing import BillingPlanFeaturesOut

FREE_MAX_VIDEO_LENGTH_SECONDS = 15 * 60
FREE_MAX_VIDEOS_PER_MONTH = 10
FREE_MAX_CHAT_MESSAGES_PER_DAY = 50


def is_pro(user: User) -> bool:
    return (user.plan or "free") == "pro"


def apply_pro_expiry_if_due(db: Session, user: User) -> User:
    """Downgrade Pro to free when a scheduled cancellation date has passed."""

    if (user.plan or "free") != UserPlan.pro.value:
        return user
    expires = user.pro_expires_at
    if expires is None:
        return user

    now = datetime.now(timezone.utc)
    exp = expires if expires.tzinfo is not None else expires.replace(tzinfo=timezone.utc)
    if exp < now:
        user.plan = UserPlan.free.value
        user.pro_expires_at = None
        db.commit()
        db.refresh(user)
    return user


def ensure_pdf_download_allowed(user: User) -> None:
    if not is_pro(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PDF download is a Pro feature. Upgrade to Pro!",
        )


def ensure_detailed_summary_allowed(user: User, *, summary_type: str) -> None:
    if not is_pro(user) and summary_type == "detailed":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Detailed summary is a Pro feature. Upgrade to Pro!",
        )


def ensure_quiz_regeneration_allowed(db: Session, *, user: User, video_id: int) -> None:
    if is_pro(user):
        return
    existing = db.scalar(select(Mcq.id).where(Mcq.video_id == video_id).limit(1))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Regenerating quiz is a Pro feature. Upgrade to Pro!",
        )


def ensure_chat_limit_allowed(db: Session, *, user: User) -> None:
    if is_pro(user):
        return
    # Teachers are not subject to learner free-tier chat caps (role may be stored as str or enum).
    role = user.role
    if role == UserRole.teacher or role == UserRole.teacher.value:
        return
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    messages_today = int(
        db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.user_id == user.id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= today_start,
            ),
        )
        or 0
    )
    if messages_today >= FREE_MAX_CHAT_MESSAGES_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Free plan allows 50 messages per day. Upgrade to Pro!",
        )


def ensure_video_upload_allowed(db: Session, *, user: User, duration_seconds: float | None) -> None:
    if is_pro(user):
        return

    if duration_seconds is not None and duration_seconds > FREE_MAX_VIDEO_LENGTH_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Free plan allows max 15 minute videos. Upgrade to Pro!",
        )

    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    videos_this_month = int(
        db.scalar(
            select(func.count())
            .select_from(Video)
            .where(
                Video.uploaded_by == user.id,
                Video.created_at >= month_start,
            ),
        )
        or 0
    )
    if videos_this_month >= FREE_MAX_VIDEOS_PER_MONTH:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Free plan allows max 10 videos per month. Upgrade to Pro!",
        )


def get_plan_features(plan: str) -> BillingPlanFeaturesOut:
    if plan == "pro":
        return BillingPlanFeaturesOut(
            max_video_length_minutes=None,
            max_videos_per_month=None,
            chatbot_messages_per_day=None,
            pdf_download=True,
            detailed_summary=True,
            regenerate_quiz=True,
        )
    return BillingPlanFeaturesOut(
        max_video_length_minutes=15,
        max_videos_per_month=10,
        chatbot_messages_per_day=50,
        pdf_download=False,
        detailed_summary=False,
        regenerate_quiz=False,
    )
