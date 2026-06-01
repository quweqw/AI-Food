from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Sex = Literal["male", "female", "other"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
Goal = Literal["balanced", "weight_loss", "muscle_gain"]


class ProfileData(BaseModel):
    email: Optional[str] = None
    name: str = ""
    sex: Sex = "male"
    gender: Optional[str] = None
    age: int = Field(default=25, ge=10, le=100)
    height_cm: int = Field(default=175, ge=80, le=250)
    height: Optional[int] = None
    weight_kg: float = Field(default=70.0, ge=25, le=350)
    weight: Optional[float] = None
    activity_level: ActivityLevel = "moderate"
    goal: Goal = "balanced"
    diet_type: Optional[str] = None
    target_calories: int = Field(default=2000, ge=900, le=5000)
    daily_calories: Optional[int] = None
    meals_per_day: int = Field(default=3, ge=1, le=6)
    allergies: List[str] = Field(default_factory=list)
    allergens: List[str] = Field(default_factory=list)
    preferred_ingredients: List[str] = Field(default_factory=list)
    favorite_products: List[str] = Field(default_factory=list)
    disliked_ingredients: List[str] = Field(default_factory=list)
    disliked_products: List[str] = Field(default_factory=list)
    excluded_ingredients: List[str] = Field(default_factory=list)
    excluded_products: List[str] = Field(default_factory=list)
    push_notifications: bool = True


class ProfileResponse(BaseModel):
    profile: ProfileData


class CalorieCalculationRequest(BaseModel):
    sex: Sex = "male"
    age: int = Field(default=25, ge=10, le=100)
    height_cm: int = Field(default=175, ge=80, le=250)
    weight_kg: float = Field(default=70.0, ge=25, le=350)
    activity_level: ActivityLevel = "moderate"
    goal: Goal = "balanced"


class CalorieCalculationResponse(BaseModel):
    bmr: int
    tdee: int
    target_calories: int
    formula: str = "mifflin_st_jeor"
    goal_adjustment: int
    explanation: str
