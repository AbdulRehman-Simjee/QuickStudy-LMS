from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User, UserPlan
from app.schemas.billing import (
    BillingCancelOut,
    BillingDowngradeOut,
    BillingPlanOut,
    BillingUpgradeIn,
    BillingUpgradeOut,
)
from app.services.plan_service import apply_pro_expiry_if_due, get_plan_features

logger = get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.post("/upgrade", response_model=BillingUpgradeOut)
def upgrade_plan(
    body: BillingUpgradeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillingUpgradeOut:
    """Mock upgrade endpoint: validates payload and sets plan to pro."""

    current_user.plan = body.plan
    current_user.pro_expires_at = None
    db.commit()
    db.refresh(current_user)
    logger.info("Plan upgraded", extra={"email": current_user.email, "plan": current_user.plan})
    return BillingUpgradeOut(message="Upgraded to Pro!", plan=current_user.plan)


@router.post("/cancel", response_model=BillingCancelOut)
def cancel_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillingCancelOut:
    """Schedule Pro cancellation; access continues until ``pro_expires_at``."""

    if (current_user.plan or "free") != UserPlan.pro.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only Pro subscribers can cancel.")

    next_month = datetime.now(timezone.utc) + timedelta(days=30)
    current_user.pro_expires_at = next_month
    db.commit()
    db.refresh(current_user)

    expires_label = next_month.strftime("%Y-%m-%d")
    logger.info("Plan cancelled", extra={"email": current_user.email, "pro_expires_at": expires_label})
    return BillingCancelOut(
        message=f"Plan cancelled. Pro access continues until {expires_label}",
        pro_expires_at=next_month,
    )


@router.post("/downgrade", response_model=BillingDowngradeOut)
def downgrade_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillingDowngradeOut:
    """Downgrade current user plan to free immediately."""

    current_user.plan = "free"
    current_user.pro_expires_at = None
    db.commit()
    db.refresh(current_user)
    return BillingDowngradeOut(message="Downgraded to Free!", plan=current_user.plan)


@router.get("/plan", response_model=BillingPlanOut)
def get_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BillingPlanOut:
    """Return current plan and feature set."""

    user = apply_pro_expiry_if_due(db, current_user)
    plan = (user.plan or "free").lower()
    cancellation_pending = plan == UserPlan.pro.value and user.pro_expires_at is not None
    return BillingPlanOut(
        plan=plan,
        features=get_plan_features(plan),
        pro_expires_at=user.pro_expires_at,
        cancellation_pending=cancellation_pending,
    )
