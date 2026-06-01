from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Goal = Literal["balanced", "weight_loss", "muscle_gain"]
PortionMode = Literal["single_user", "cook_for_people"]
MealProgressStatus = Literal["planned", "cooked", "eaten", "skipped"]
MealPlannerIntent = Literal["generate_meal_plan", "suggest_dinner", "unknown"]


class TemporaryOverrides(BaseModel):
    target_calories: Optional[int] = None
    goal: Optional[Goal] = None
    meals_per_day: Optional[int] = None
    excluded: List[str] = Field(default_factory=list)
    excluded_ingredients: List[str] = Field(default_factory=list)
    preferred: List[str] = Field(default_factory=list)
    preferred_ingredients: List[str] = Field(default_factory=list)
    disliked: List[str] = Field(default_factory=list)
    disliked_ingredients: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    allergens: List[str] = Field(default_factory=list)


class GenerateMealPlanRequest(BaseModel):
    days: int = 7
    meals_per_day: Optional[int] = None
    goal: Optional[Goal] = None
    target_calories: Optional[int] = None
    servings: int = 1
    people_count: int = 1
    portion_mode: PortionMode = "single_user"
    temporary_overrides: TemporaryOverrides = Field(default_factory=TemporaryOverrides)
    save_to_profile: bool = False


class DinnerSuggestionRequest(BaseModel):
    meal_type: str = "dinner"
    target_calories: Optional[int] = None
    servings: int = 1
    people_count: int = 1
    ingredients_available: List[str] = Field(default_factory=list)
    temporary_overrides: TemporaryOverrides = Field(default_factory=TemporaryOverrides)


class IntentParseRequest(BaseModel):
    message: str
    current_profile: Dict[str, Any] = Field(default_factory=dict)


class MealPlannerError(BaseModel):
    code: str
    message: str
    missing_fields: List[str] = Field(default_factory=list)
    can_continue_with_defaults: bool = False


class MealNutrition(BaseModel):
    calories: float = 0.0
    protein: float = 0.0
    fat: float = 0.0
    carbs: float = 0.0


class MealProgress(BaseModel):
    status: MealProgressStatus = "planned"
    checked: bool = False
    completed_at: Optional[str] = None
    user_note: str = ""


class MealRecipe(BaseModel):
    id: str
    name: str
    image_url: Optional[str] = None
    ingredients: List[Any] = Field(default_factory=list)
    ingredients_detail: List[Any] = Field(default_factory=list)
    instructions: List[str] = Field(default_factory=list)
    serving_model: Dict[str, Any] = Field(default_factory=dict)
    scaling: Dict[str, Any] = Field(default_factory=dict)


class MealPlanMeal(BaseModel):
    meal_id: str
    slot: int
    meal_type: str
    name: str
    score: float = 0.0
    tier: str = "normal"
    servings: int = 1
    servings_total: int = 1
    people_count: int = 1
    eaten_weight_g: float = 0.0
    cooking_total_weight_g: float = 0.0
    user_eaten_weight_g: float = 0.0
    nutrition: MealNutrition = Field(default_factory=MealNutrition)
    nutrition_total: MealNutrition = Field(default_factory=MealNutrition)
    nutrition_per_serving: MealNutrition = Field(default_factory=MealNutrition)
    nutrition_for_user: MealNutrition = Field(default_factory=MealNutrition)
    main_carb: Optional[str] = None
    main_proteins: List[str] = Field(default_factory=list)
    recipe: MealRecipe
    progress: MealProgress = Field(default_factory=MealProgress)


class MealPlanDay(BaseModel):
    day: int
    score: float = 0.0
    target_calories: float = 0.0
    actual_calories: float = 0.0
    macro_summary: MealNutrition = Field(default_factory=MealNutrition)
    meals: List[MealPlanMeal] = Field(default_factory=list)


class PlanProgress(BaseModel):
    plan_id: str
    days_total: int = 0
    days_completed: int = 0
    meals_total: int = 0
    meals_completed: int = 0
    completion_percent: float = 0.0
    current_day: int = 1


class MealPlanSummary(BaseModel):
    generated_meals: int = 0
    empty_slots: int = 0
    normal: int = 0
    relaxed: int = 0
    emergency: int = 0
    avg_calorie_error: float = 0.0
    avg_protein_error: float = 0.0
    avg_fat_error: float = 0.0
    avg_carbs_error: float = 0.0


class MealPlanResponse(BaseModel):
    plan_id: str
    days: List[MealPlanDay] = Field(default_factory=list)
    summary: MealPlanSummary = Field(default_factory=MealPlanSummary)
    progress: PlanProgress
    warnings: List[str] = Field(default_factory=list)


class DinnerSuggestionResponse(BaseModel):
    suggestions: List[MealPlanMeal] = Field(default_factory=list)


class IntentParseResponse(BaseModel):
    intent: MealPlannerIntent = "unknown"
    confidence: float = 0.0
    extracted_parameters: Dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    confirmation_message: str = ""
    actions: List[str] = Field(default_factory=list)


class ProgressUpdateRequest(BaseModel):
    status: Optional[MealProgressStatus] = None
    checked: Optional[bool] = None
    completed_at: Optional[str] = None
    user_note: Optional[str] = None


class ProgressUpdateResponse(BaseModel):
    plan_id: str
    meal_id: str
    meal_progress: MealProgress
    plan_progress: PlanProgress
    updated_at: datetime
