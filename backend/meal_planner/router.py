from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth.service import decode_token
from database.db import get_db
from meal_planner import service
from meal_planner.schemas import (
    DinnerSuggestionRequest,
    DinnerSuggestionResponse,
    GenerateMealPlanRequest,
    IntentParseRequest,
    IntentParseResponse,
    MealPlanResponse,
    ProgressUpdateRequest,
    ProgressUpdateResponse,
)


router = APIRouter(prefix="/meal-planner", tags=["meal-planner"])
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    email = decode_token(credentials.credentials)
    if not email:
        raise HTTPException(401, "Invalid token")
    return email


@router.post("/generate", response_model=MealPlanResponse)
async def generate_meal_plan(
    data: GenerateMealPlanRequest,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.generate_plan(db, user_email, data)


@router.post("/dinner-suggestion", response_model=DinnerSuggestionResponse)
async def dinner_suggestion(
    data: DinnerSuggestionRequest,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.dinner_suggestion(db, user_email, data)


@router.post("/intent/parse", response_model=IntentParseResponse)
async def parse_intent(
    data: IntentParseRequest,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.parse_message_intent(
        db=db,
        user_email=user_email,
        message=data.message,
        current_profile=data.current_profile,
    )


@router.get("/latest", response_model=MealPlanResponse)
async def latest_plan(
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_latest_plan(db, user_email)


@router.get("/{plan_id}", response_model=MealPlanResponse)
async def get_plan(
    plan_id: str,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_plan(db, user_email, plan_id)


@router.patch(
    "/{plan_id}/meals/{meal_id}/progress",
    response_model=ProgressUpdateResponse,
)
async def update_progress(
    plan_id: str,
    meal_id: str,
    data: ProgressUpdateRequest,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_meal_progress(
        db=db,
        user_email=user_email,
        plan_id=plan_id,
        meal_id=meal_id,
        request=data,
    )


@router.post("/{plan_id}/meals/{meal_id}/replace", response_model=MealPlanResponse)
async def replace_meal(
    plan_id: str,
    meal_id: str,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.replace_meal(
        db=db,
        user_email=user_email,
        plan_id=plan_id,
        meal_id=meal_id,
        regenerate=False,
    )


@router.post("/{plan_id}/meals/{meal_id}/regenerate", response_model=MealPlanResponse)
async def regenerate_meal(
    plan_id: str,
    meal_id: str,
    user_email: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.replace_meal(
        db=db,
        user_email=user_email,
        plan_id=plan_id,
        meal_id=meal_id,
        regenerate=True,
    )
