from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.settings import (
    SettingsAvatarUrlOut,
    SettingsChangePasswordIn,
    SettingsMessageOut,
    SettingsProfileOut,
    SettingsProfilePatchIn,
)
from app.services.avatar_service import avatar_public_path, read_and_save_avatar_jpeg, remove_avatar_file
from app.services.settings_service import purge_user_account, update_user_full_name
from app.utils.security import hash_password, verify_password

router = APIRouter(prefix="/settings", tags=["Settings"])


def _profile_out(user: User) -> SettingsProfileOut:
    return SettingsProfileOut(
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        plan=user.plan,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
    )


@router.get("/profile", response_model=SettingsProfileOut)
def get_profile(current_user: User = Depends(get_current_user)) -> SettingsProfileOut:
    return _profile_out(current_user)


@router.patch("/profile-picture", response_model=SettingsAvatarUrlOut)
async def patch_profile_picture(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    file: UploadFile = File(...),
) -> SettingsAvatarUrlOut:
    ct = (file.content_type or "").split(";")[0].strip().lower()
    if ct and ct not in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Allowed types: JPG, PNG, WebP.",
        )

    await read_and_save_avatar_jpeg(user_id=current_user.id, upload=file)
    url = avatar_public_path(current_user.id)
    current_user.avatar_url = url
    db.commit()
    db.refresh(current_user)
    return SettingsAvatarUrlOut(avatar_url=url)


@router.delete("/profile-picture", response_model=SettingsMessageOut)
def delete_profile_picture(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsMessageOut:
    remove_avatar_file(current_user.id)
    current_user.avatar_url = None
    db.commit()
    return SettingsMessageOut(message="Profile picture removed.")


@router.patch("/profile", response_model=SettingsProfileOut)
def patch_profile(
    body: SettingsProfilePatchIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsProfileOut:
    updated = update_user_full_name(db, user=current_user, full_name=body.full_name)
    return _profile_out(updated)


@router.post("/change-password", response_model=SettingsMessageOut)
def change_password(
    body: SettingsChangePasswordIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsMessageOut:
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.password_hash = hash_password(body.new_password)
    db.commit()
    return SettingsMessageOut(message="Password updated successfully")


@router.delete("/account", response_model=SettingsMessageOut)
def delete_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsMessageOut:
    uid = current_user.id
    purge_user_account(db, user_id=uid)
    return SettingsMessageOut(message="Your account and associated data have been deleted.")
