from pydantic import BaseModel
from typing import List

class UserSettingsRequest(BaseModel):
    name: str = ""
    age: int = 25
    gender: str = "male"
    height: int = 175
    weight: float = 70.0
    activity_level: str = "moderate"
    daily_calories: int = 2000
    diet_type: str = "normal"
    meals_per_day: int = 3
    allergens: List[str] = []
    favorite_products: List[str] = []
    disliked_products: List[str] = []
    excluded_products: List[str] = []
    push_notifications: bool = True

class UserSettingsResponse(UserSettingsRequest):
    email: str
