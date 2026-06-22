from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, MessageResponse, SignupRequest, UserPublic
from app.services.auth_service import authenticate_user, create_user, get_user_by_email
from app.services.plan_service import apply_pro_expiry_if_due
from app.utils.security import create_access_token

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _user_public(db: Session, user: User) -> UserPublic:
    user = apply_pro_expiry_if_due(db, user)
    return UserPublic(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        plan=user.plan,
        avatar_url=user.avatar_url,
        pro_expires_at=user.pro_expires_at,
        created_at=user.created_at,
    )


@router.post("/signup", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """
    Create a new user account.
    """

    existing = get_user_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    try:
        create_user(
            db,
            full_name=payload.full_name.strip(),
            email=str(payload.email),
            password=payload.password,
            role=payload.role,
        )
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    logger.info("User signup", extra={"email": str(payload.email), "role": payload.role.value})
    return MessageResponse(message="Signup successful")


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    """
    Authenticate a user and return a JWT access token.
    """

    user = authenticate_user(db, email=str(payload.email), password=payload.password)
    if user is None:
        logger.warning("Login failed", extra={"email": str(payload.email)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    logger.info("User login success", extra={"email": user.email})
    token = create_access_token(subject=str(user.id))

    return AuthResponse(
        access_token=token,
        user=_user_public(db, user),
    )


@router.get("/me", response_model=UserPublic)
def me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    """
    Get details for the currently authenticated user.
    """

    return _user_public(db, current_user)
