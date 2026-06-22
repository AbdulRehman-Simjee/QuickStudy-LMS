from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class BillingUpgradeIn(BaseModel):
    plan: str = Field(..., description="Target plan; only 'pro' is accepted.")
    card_number: str
    expiry: str
    cvv: str
    name_on_card: str

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, value: str) -> str:
        v = (value or "").strip().lower()
        if v != "pro":
            raise ValueError("Only 'pro' is allowed for upgrade")
        return v

    @field_validator("card_number", "expiry", "cvv", "name_on_card")
    @classmethod
    def validate_required_fields(cls, value: str) -> str:
        if not (value or "").strip():
            raise ValueError("Field cannot be empty")
        return value.strip()


class BillingUpgradeOut(BaseModel):
    message: str
    plan: str


class BillingDowngradeOut(BaseModel):
    message: str
    plan: str


class BillingCancelOut(BaseModel):
    message: str
    pro_expires_at: datetime


class BillingPlanFeaturesOut(BaseModel):
    max_video_length_minutes: int | None
    max_videos_per_month: int | None
    chatbot_messages_per_day: int | None
    pdf_download: bool
    detailed_summary: bool
    regenerate_quiz: bool


class BillingPlanOut(BaseModel):
    plan: str
    features: BillingPlanFeaturesOut
    pro_expires_at: datetime | None = None
    cancellation_pending: bool = False
