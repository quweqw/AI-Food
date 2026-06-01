from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth.service import auth_error, decode_token, get_user_by_email
from database.db import get_db
from database.models import User
from .schemas import (
    CalorieCalculationRequest,
    CalorieCalculationResponse,
    ProfileData,
    ProfileResponse,
)
from .service import (
    apply_profile_to_user,
    calculate_calories,
    profile_email_change_requested,
    profile_from_user,
)


router = APIRouter(prefix="/profile", tags=["profile"])
security = HTTPBearer()


async def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    email = decode_token(credentials.credentials)
    if not email:
        raise auth_error(401, "INVALID_TOKEN", "Невалидный токен")
    user = await get_user_by_email(email, db)
    if not user:
        raise auth_error(401, "INVALID_TOKEN", "Пользователь не найден")
    return user


@router.get("", response_model=ProfileResponse)
async def get_profile(user: User = Depends(current_user)):
    return ProfileResponse(profile=profile_from_user(user))


@router.put("", response_model=ProfileResponse)
async def put_profile(
    data: ProfileData,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if profile_email_change_requested(user, data):
        raise auth_error(
            400,
            "EMAIL_CHANGE_NOT_ALLOWED",
            "Email аккаунта нельзя изменить",
        )
    apply_profile_to_user(user, data, partial=False)
    await db.commit()
    await db.refresh(user)
    return ProfileResponse(profile=profile_from_user(user))


@router.patch("", response_model=ProfileResponse)
async def patch_profile(
    data: ProfileData,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if profile_email_change_requested(user, data):
        raise auth_error(
            400,
            "EMAIL_CHANGE_NOT_ALLOWED",
            "Email аккаунта нельзя изменить",
        )
    apply_profile_to_user(user, data, partial=True)
    await db.commit()
    await db.refresh(user)
    return ProfileResponse(profile=profile_from_user(user))


@router.post("/calculate-calories", response_model=CalorieCalculationResponse)
async def calculate_profile_calories(data: CalorieCalculationRequest):
    return calculate_calories(data)
