from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.db import get_db
from database.models import User
from auth.service import decode_token
from users.models import UserSettingsRequest, UserSettingsResponse



router = APIRouter(prefix="/users", tags=["users"])
security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    email = decode_token(credentials.credentials)
    if not email:
        raise HTTPException(401, "Невалидный токен")
    return email

@router.get("/settings", response_model=UserSettingsResponse)
async def get_settings(
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where(User.email == user_email)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    return UserSettingsResponse(
        email=user.email,
        name=user.name or "",
        age=user.age or 25,
        gender=user.gender or "male",
        height=user.height or 175,
        weight=user.weight or 70.0,
        activity_level=user.activity_level or "moderate",
        daily_calories=user.daily_calories or 2000,
        diet_type=user.diet_type or "normal",
        meals_per_day=user.meals_per_day or 3,
        allergens=user.allergens.split(",") if user.allergens else [],
        favorite_products=user.favorite_products.split(",") if user.favorite_products else [],
        disliked_products=user.disliked_products.split(",") if user.disliked_products else [],
        excluded_products=user.excluded_products.split(",") if user.excluded_products else [],
        push_notifications=(
            user.push_notifications if user.push_notifications is not None else True
        ),
    )

@router.put("/settings")
async def update_settings(
    data: UserSettingsRequest,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where(User.email == user_email)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    user.name = data.name
    user.age = data.age
    user.gender = data.gender
    user.height = data.height
    user.weight = data.weight
    user.activity_level = data.activity_level
    user.daily_calories = data.daily_calories
    user.diet_type = data.diet_type
    user.meals_per_day = data.meals_per_day
    user.allergens = ",".join(data.allergens)
    user.favorite_products = ",".join(data.favorite_products)
    user.disliked_products = ",".join(data.disliked_products)
    user.excluded_products = ",".join(data.excluded_products)
    user.push_notifications = data.push_notifications

    await db.commit()
    return {"status": "ok"}
