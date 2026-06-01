from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, List

from database.models import User
from .schemas import (
    CalorieCalculationRequest,
    CalorieCalculationResponse,
    ProfileData,
)


ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


def profile_from_user(user: User) -> ProfileData:
    goal = goal_from_diet_type(user.diet_type)
    allergies = split_csv(user.allergens)
    preferred = split_csv(user.favorite_products)
    disliked = split_csv(getattr(user, "disliked_products", ""))
    excluded = split_csv(user.excluded_products)
    return ProfileData(
        email=user.email,
        name=user.name or "",
        sex=(user.gender or "male"),
        gender=user.gender or "male",
        age=user.age or 25,
        height_cm=user.height or 175,
        height=user.height or 175,
        weight_kg=user.weight or 70.0,
        weight=user.weight or 70.0,
        activity_level=user.activity_level or "moderate",
        goal=goal,
        diet_type=diet_type_from_goal(goal),
        target_calories=user.daily_calories or 2000,
        daily_calories=user.daily_calories or 2000,
        meals_per_day=user.meals_per_day or 3,
        allergies=allergies,
        allergens=allergies,
        preferred_ingredients=preferred,
        favorite_products=preferred,
        disliked_ingredients=disliked,
        disliked_products=disliked,
        excluded_ingredients=excluded,
        excluded_products=excluded,
        push_notifications=(
            user.push_notifications if user.push_notifications is not None else True
        ),
    )


def profile_email_change_requested(user: User, profile: ProfileData) -> bool:
    fields_set = getattr(profile, "model_fields_set", set())
    if "email" not in fields_set:
        return False
    requested_email = str(profile.email or "").strip().lower()
    current_email = str(user.email or "").strip().lower()
    return requested_email != current_email


def apply_profile_to_user(user: User, profile: ProfileData, partial: bool = False) -> None:
    data = profile.model_dump(exclude_unset=partial)

    def has(*keys: str) -> bool:
        return any(key in data and data[key] is not None for key in keys)

    def first(*keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return default

    if has("name"):
        user.name = str(first("name", default="")).strip()
    if has("sex", "gender"):
        user.gender = str(first("sex", "gender", default="male"))
    if has("age"):
        user.age = int(first("age", default=25))
    if has("height_cm", "height"):
        user.height = int(first("height_cm", "height", default=175))
    if has("weight_kg", "weight"):
        user.weight = float(first("weight_kg", "weight", default=70.0))
    if has("activity_level"):
        user.activity_level = str(first("activity_level", default="moderate"))
    if has("goal", "diet_type"):
        user.diet_type = diet_type_from_goal(goal_from_value(first("goal", "diet_type")))
    if has("target_calories", "daily_calories"):
        user.daily_calories = int(first("target_calories", "daily_calories", default=2000))
    if has("meals_per_day"):
        user.meals_per_day = int(first("meals_per_day", default=3))
    if has("allergies", "allergens"):
        user.allergens = join_csv(first("allergies", "allergens", default=[]))
    if has("preferred_ingredients", "favorite_products"):
        user.favorite_products = join_csv(
            first("preferred_ingredients", "favorite_products", default=[])
        )
    if has("disliked_ingredients", "disliked_products"):
        user.disliked_products = join_csv(
            first("disliked_ingredients", "disliked_products", default=[])
        )
    if has("excluded_ingredients", "excluded_products"):
        user.excluded_products = join_csv(
            first("excluded_ingredients", "excluded_products", default=[])
        )
    if has("push_notifications"):
        user.push_notifications = bool(first("push_notifications", default=True))

    user.updated_at = datetime.utcnow()


def calculate_calories(data: CalorieCalculationRequest) -> CalorieCalculationResponse:
    if data.sex == "female":
        bmr = 10 * data.weight_kg + 6.25 * data.height_cm - 5 * data.age - 161
    else:
        bmr = 10 * data.weight_kg + 6.25 * data.height_cm - 5 * data.age + 5

    multiplier = ACTIVITY_MULTIPLIERS[data.activity_level]
    tdee = int(round(bmr * multiplier))
    adjustment = goal_adjustment(data.goal)
    target = max(1200 if data.sex == "female" else 1500, min(5000, tdee + adjustment))

    if data.goal == "weight_loss":
        explanation = f"Для похудения применён дефицит {abs(adjustment)} ккал."
    elif data.goal == "muscle_gain":
        explanation = f"Для набора массы применён профицит {adjustment} ккал."
    else:
        explanation = "Для обычного режима калорийность оставлена на уровне TDEE."

    return CalorieCalculationResponse(
        bmr=int(round(bmr)),
        tdee=tdee,
        target_calories=int(round(target)),
        goal_adjustment=adjustment,
        explanation=explanation,
    )


def goal_adjustment(goal: str) -> int:
    if goal == "weight_loss":
        return -450
    if goal == "muscle_gain":
        return 300
    return 0


def goal_from_value(value: Any) -> str:
    raw = str(value or "balanced").lower()
    if raw in {"cut", "weight_loss", "сушка", "похудение"}:
        return "weight_loss"
    if raw in {"bulk", "muscle_gain", "массонабор", "набор"}:
        return "muscle_gain"
    return "balanced"


def goal_from_diet_type(value: Any) -> str:
    return goal_from_value(value)


def diet_type_from_goal(goal: str) -> str:
    if goal == "weight_loss":
        return "cut"
    if goal == "muscle_gain":
        return "bulk"
    return "normal"


def split_csv(value: Any) -> List[str]:
    if isinstance(value, list):
        return clean_list(value)
    return clean_list(str(value or "").split(","))


def join_csv(values: Iterable[Any]) -> str:
    return ",".join(clean_list(values))


def clean_list(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for value in values or []:
        item = str(value).strip()
        if item and item not in result:
            result.append(item)
    return result
