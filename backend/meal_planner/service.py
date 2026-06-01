from __future__ import annotations

import json
import os
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import MealPlan, User
try:
    from food_terms import expand_food_terms
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from backend.food_terms import expand_food_terms
from meal_planner.intent_parser import parse_intent
from meal_planner.localization import (
    localize_food_name,
    localize_ingredients,
    localize_instruction,
    localize_meal_type,
    localize_title,
    parse_instruction_lines,
)
from meal_planner.schemas import (
    DinnerSuggestionRequest,
    DinnerSuggestionResponse,
    GenerateMealPlanRequest,
    IntentParseResponse,
    MealNutrition,
    MealPlanDay,
    MealPlanMeal,
    MealPlanResponse,
    MealPlanSummary,
    MealProgress,
    MealRecipe,
    PlanProgress,
    ProgressUpdateRequest,
    ProgressUpdateResponse,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ai.core.user_profile import UserProfile  # noqa: E402


_planner = None


def get_planner():
    global _planner
    if _planner is not None:
        return _planner

    from ai.core.decision.portion_optimizer import PortionOptimizer
    from ai.core.meal_planner import MealPlanner
    from ai.llm.nutrition_engine import NutritionEngine
    from ai.recipes.recipe_search import RecipeSearch

    engine = NutritionEngine()
    recipe_search = RecipeSearch()
    optimizer = PortionOptimizer(engine)

    _planner = MealPlanner(
        recipe_search=recipe_search,
        nutrition_engine=engine,
        portion_optimizer=optimizer,
        safety_checker=_optional_instance("ai.core.decision.safety_checker", "SafetyChecker"),
        preference_scorer=_optional_instance("ai.core.decision.preference_scorer", "PreferenceScorer"),
        diversity_engine=_optional_instance("ai.core.decision.diversity_engine", "DiversityEngine"),
        substitution_engine=_optional_instance("ai.core.decision.substitution_engine", "SubstitutionEngine"),
        llm=None,
    )
    return _planner


def _optional_instance(module_name: str, class_name: str):
    try:
        module = __import__(module_name, fromlist=[class_name])
        return getattr(module, class_name)()
    except Exception:
        return None


async def get_user(db: AsyncSession, user_email: str) -> User:
    result = await db.execute(select(User).where(User.email == user_email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, {"error": {"code": "USER_NOT_FOUND", "message": "User not found"}})
    return user


async def parse_message_intent(
    db: AsyncSession,
    user_email: str,
    message: str,
    current_profile: Optional[Dict[str, Any]] = None,
) -> IntentParseResponse:
    user = await get_user(db, user_email)
    profile = _profile_dict(user)
    profile.update(current_profile or {})
    return parse_intent(message, profile)


async def generate_plan(
    db: AsyncSession,
    user_email: str,
    request: GenerateMealPlanRequest,
) -> MealPlanResponse:
    user = await get_user(db, user_email)
    warnings = _profile_warnings(user)

    if request.save_to_profile:
        _apply_request_to_user(user, request)
        await db.commit()
        await db.refresh(user)

    user_profile = _build_user_profile(user, request)
    planner = get_planner()

    try:
        raw_plan = planner.build_plan(
            user_profile=user_profile,
            days=max(1, min(14, int(request.days or 7))),
            candidate_limit=int(os.getenv("AI_FOOD_PROD_CANDIDATES", "80")),
            explain_with_llm=False,
        )
    except Exception as exc:
        raise HTTPException(
            500,
            {
                "error": {
                    "code": "MEAL_PLANNER_FAILED",
                    "message": str(exc),
                    "missing_fields": [],
                    "can_continue_with_defaults": False,
                }
            },
        ) from exc

    response = normalize_plan_response(
        raw_plan=raw_plan,
        request=request,
        warnings=warnings,
    )

    row = MealPlan(
        id=response.plan_id,
        user_email=user_email,
        request_json=_json_dumps(request.model_dump()),
        response_json=_json_dumps(response.model_dump()),
        progress_json=_json_dumps(response.progress.model_dump()),
    )
    db.add(row)
    await db.commit()

    return response


async def dinner_suggestion(
    db: AsyncSession,
    user_email: str,
    request: DinnerSuggestionRequest,
) -> DinnerSuggestionResponse:
    user = await get_user(db, user_email)
    overrides = request.temporary_overrides.model_copy(deep=True)
    if request.ingredients_available:
        preferred = (
            overrides.preferred
            or overrides.preferred_ingredients
            or []
        )
        overrides.preferred = list(dict.fromkeys([*request.ingredients_available, *preferred]))
    generation_request = GenerateMealPlanRequest(
        days=1,
        meals_per_day=3,
        goal=overrides.goal,
        target_calories=request.target_calories,
        servings=request.servings,
        people_count=request.people_count,
        temporary_overrides=overrides,
    )
    user_profile = _build_user_profile(user, generation_request)
    planner = get_planner()
    goal = planner._normalize_goal(getattr(user_profile, "goal", "balanced"))
    target_calories = int(request.target_calories or getattr(user_profile, "target_calories", 2000))
    macro_targets = planner._get_macro_targets(target_calories, goal, user_profile)
    meals_per_day = planner._clamp_meals_per_day(getattr(user_profile, "meals_per_day", 3))
    meal_type = request.meal_type or "dinner"
    slot_idx = _slot_index_for_meal_type(planner, meal_type, meals_per_day)
    weights = planner._meal_weights(meals_per_day, goal)
    slot_weight = weights[slot_idx]
    slot_target = target_calories * slot_weight
    slot_macros = planner._slot_macro_targets(macro_targets, slot_weight)

    candidates = planner._fetch_slot_candidates(
        user_profile=user_profile,
        goal=goal,
        meal_type=meal_type,
        slot_target_calories=slot_target,
        slot_target_macros=slot_macros,
        candidate_limit=80,
        used_main_carbs=[],
        plan_main_carbs=[],
    )
    optimized = planner._prefilter_candidates_for_slot(
        candidates=candidates,
        meal_type=meal_type,
        user_profile=user_profile,
        selected_signatures=set(),
        used_main_carbs=set(),
        limit=min(12, len(candidates)),
    )

    scored: List[Dict[str, Any]] = []
    for recipe in optimized:
        item = planner._score_candidate(
            recipe,
            user_profile=user_profile,
            target_calories=target_calories,
            goal=goal,
            slot_target_calories=slot_target,
            slot_macro_targets=slot_macros,
            current_totals=planner._empty_day_totals(),
            macro_targets=macro_targets,
            meal_type=meal_type,
            recent_recipe_names=[],
        )
        if item.get("reject"):
            continue
        meal = {
            "meal_type": meal_type,
            "target_calories": round(slot_target, 1),
            "target_macros": slot_macros,
            "name": recipe.get("name", "Meal"),
            "ingredients": item.get("optimized_ingredients", recipe.get("ingredients", [])),
            "portion": item.get("optimized_portion", {}),
            "nutrition": item.get("nutrition", {}),
            "score": item.get("score", 0.0),
            "selection_tier": item.get("selection_tier", "normal"),
            "components": item.get("components", {}),
            "instructions": recipe.get("instructions", []),
            "cuisine": recipe.get("cuisine"),
        }
        scored.append(meal)

    scored.sort(key=lambda value: float(value.get("score", 0.0) or 0.0), reverse=True)
    suggestions = [
        _normalize_meal(
            meal=meal,
            day_number=1,
            slot_index=index + 1,
            request=generation_request,
        )
        for index, meal in enumerate(scored[:3])
    ]

    if not suggestions:
        raise HTTPException(
            404,
            {
                "error": {
                    "code": "NO_SAFE_CANDIDATES",
                    "message": "No safe dinner candidates found",
                    "missing_fields": [],
                    "can_continue_with_defaults": True,
                }
            },
        )

    return DinnerSuggestionResponse(suggestions=suggestions)


async def get_latest_plan(db: AsyncSession, user_email: str) -> MealPlanResponse:
    result = await db.execute(
        select(MealPlan)
        .where(MealPlan.user_email == user_email)
        .order_by(desc(MealPlan.created_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise _plan_not_found()
    return _localize_response(MealPlanResponse.model_validate_json(row.response_json))


async def get_plan(db: AsyncSession, user_email: str, plan_id: str) -> MealPlanResponse:
    row = await _get_plan_row(db, user_email, plan_id)
    return _localize_response(MealPlanResponse.model_validate_json(row.response_json))


async def update_meal_progress(
    db: AsyncSession,
    user_email: str,
    plan_id: str,
    meal_id: str,
    request: ProgressUpdateRequest,
) -> ProgressUpdateResponse:
    row = await _get_plan_row(db, user_email, plan_id)
    response = _localize_response(MealPlanResponse.model_validate_json(row.response_json))

    target_meal = None
    for day in response.days:
        for meal in day.meals:
            if meal.meal_id == meal_id:
                target_meal = meal
                break
        if target_meal:
            break

    if target_meal is None:
        raise HTTPException(
            404,
            {"error": {"code": "PLAN_NOT_FOUND", "message": "Meal not found in plan"}},
        )

    progress = target_meal.progress
    if request.status is not None:
        progress.status = request.status
    if request.checked is not None:
        progress.checked = request.checked
    if request.completed_at is not None:
        progress.completed_at = request.completed_at
    elif progress.checked or progress.status in {"eaten", "skipped"}:
        progress.completed_at = datetime.utcnow().isoformat()
    if request.user_note is not None:
        progress.user_note = request.user_note

    response.progress = _build_plan_progress(response.plan_id, response.days)
    row.response_json = _json_dumps(response.model_dump())
    row.progress_json = _json_dumps(response.progress.model_dump())
    await db.commit()

    return ProgressUpdateResponse(
        plan_id=plan_id,
        meal_id=meal_id,
        meal_progress=progress,
        plan_progress=response.progress,
        updated_at=datetime.utcnow(),
    )


async def replace_meal(
    db: AsyncSession,
    user_email: str,
    plan_id: str,
    meal_id: str,
    regenerate: bool = False,
) -> MealPlanResponse:
    row = await _get_plan_row(db, user_email, plan_id)
    user = await get_user(db, user_email)
    response = _localize_response(MealPlanResponse.model_validate_json(row.response_json))
    request = _request_from_row(row)

    location = _find_meal_location(response, meal_id)
    if location is None:
        raise HTTPException(
            404,
            {"error": {"code": "PLAN_NOT_FOUND", "message": "Meal not found in plan"}},
        )

    day_index, meal_index = location
    day = response.days[day_index]
    current_meal = day.meals[meal_index]

    suggestions = await dinner_suggestion(
        db,
        user_email,
        DinnerSuggestionRequest(
            meal_type=_meal_type_to_english(current_meal.meal_type),
            target_calories=int(request.target_calories or user.daily_calories or 2000),
            servings=max(1, current_meal.servings_total or request.servings or 1),
            people_count=max(1, current_meal.people_count or request.people_count or 1),
            temporary_overrides=request.temporary_overrides,
        ),
    )

    replacement = _pick_replacement(current_meal, suggestions.suggestions, allow_same=regenerate)
    if replacement is None:
        raise HTTPException(
            404,
            {
                "error": {
                    "code": "NO_SAFE_CANDIDATES",
                    "message": "No alternative safe meal candidate found",
                    "missing_fields": [],
                    "can_continue_with_defaults": True,
                }
            },
        )

    replacement.meal_id = current_meal.meal_id
    replacement.slot = current_meal.slot
    replacement.meal_type = current_meal.meal_type
    replacement.progress = MealProgress()
    day.meals[meal_index] = replacement

    _recalculate_day(day)
    response.summary = _build_summary(response.days, request)
    response.progress = _build_plan_progress(response.plan_id, response.days)
    row.response_json = _json_dumps(response.model_dump())
    row.progress_json = _json_dumps(response.progress.model_dump())
    await db.commit()

    return response


def normalize_plan_response(
    raw_plan: Dict[str, Any],
    request: GenerateMealPlanRequest,
    warnings: Optional[List[str]] = None,
) -> MealPlanResponse:
    plan_id = str(uuid.uuid4())
    raw_days = raw_plan.get("plan", []) if isinstance(raw_plan, dict) else []
    days = [
        _normalize_day(day, request, plan_id)
        for day in raw_days
    ]
    summary = _build_summary(days, request, raw_plan.get("macro_targets", {}))
    progress = _build_plan_progress(plan_id, days)
    all_warnings = list(warnings or [])
    for day in raw_days:
        all_warnings.extend(str(item) for item in day.get("warnings", []) or [])

    return MealPlanResponse(
        plan_id=plan_id,
        days=days,
        summary=summary,
        progress=progress,
        warnings=sorted(set(all_warnings)),
    )


def _normalize_day(
    day: Dict[str, Any],
    request: GenerateMealPlanRequest,
    plan_id: str,
) -> MealPlanDay:
    day_number = int(day.get("day", 1) or 1)
    meals = [
        _normalize_meal(meal, day_number, index + 1, request)
        for index, meal in enumerate(day.get("meals", []) or [])
    ]
    totals = day.get("day_total", {}) or {}
    macros = MealNutrition(
        calories=_float(totals.get("calories")),
        protein=_float(totals.get("protein")),
        fat=_float(totals.get("fat")),
        carbs=_float(totals.get("carbs")),
    )

    return MealPlanDay(
        day=day_number,
        score=_round(day.get("day_score")),
        target_calories=_float(day.get("target_calories")),
        actual_calories=macros.calories,
        macro_summary=macros,
        meals=meals,
    )


def _normalize_meal(
    meal: Dict[str, Any],
    day_number: int,
    slot_index: int,
    request: GenerateMealPlanRequest,
) -> MealPlanMeal:
    meal_id = f"d{day_number}-s{slot_index}-{uuid.uuid4().hex[:8]}"
    nutrition_for_user = _nutrition(meal.get("nutrition", {}))
    servings = max(1, int(request.servings or 1))
    people_count = max(1, int(request.people_count or 1))
    nutrition_total = _scale_nutrition(nutrition_for_user, servings)
    nutrition_per_serving = _scale_nutrition(nutrition_total, 1 / servings)
    raw_ingredients = meal.get("ingredients", []) or []
    ingredients = localize_ingredients(raw_ingredients)
    scaled_ingredients = localize_ingredients(_scale_ingredients(raw_ingredients, servings))
    eaten_weight = _float(
        nutrition_for_user_dict(meal).get("eaten_weight_g")
        or (meal.get("portion") or {}).get("eaten_weight_g")
        or 0.0
    )
    components = meal.get("components", {}) or {}
    source_recipe_name = str(meal.get("name", "Meal") or "Meal")
    recipe_name = localize_title(source_recipe_name)

    recipe = MealRecipe(
        id=_stable_recipe_id(source_recipe_name),
        name=recipe_name,
        image_url=_image_url(meal),
        ingredients=ingredients,
        ingredients_detail=scaled_ingredients,
        instructions=_instructions(meal.get("instructions")),
        serving_model={
            "servings_total": servings,
            "people_count": people_count,
            "portion_mode": request.portion_mode,
        },
        scaling={
            "base_servings": 1,
            "scale_factor": servings,
            "scaled_ingredients": scaled_ingredients,
        },
    )

    return MealPlanMeal(
        meal_id=meal_id,
        slot=slot_index,
        meal_type=localize_meal_type(meal.get("meal_type", "meal") or "meal"),
        name=recipe_name,
        score=_round(meal.get("score")),
        tier=str(meal.get("selection_tier") or components.get("selection_quality_tier") or "normal"),
        servings=servings,
        servings_total=servings,
        people_count=people_count,
        eaten_weight_g=eaten_weight,
        cooking_total_weight_g=round(eaten_weight * servings, 1),
        user_eaten_weight_g=eaten_weight,
        nutrition=nutrition_for_user,
        nutrition_total=nutrition_total,
        nutrition_per_serving=nutrition_per_serving,
        nutrition_for_user=nutrition_for_user,
        main_carb=localize_food_name(components.get("main_carb")) if components.get("main_carb") else None,
        main_proteins=[localize_food_name(item) for item in _list_of_strings(components.get("main_proteins"))],
        recipe=recipe,
        progress=MealProgress(),
    )


def _build_summary(
    days: List[MealPlanDay],
    request: GenerateMealPlanRequest,
    macro_targets: Optional[Dict[str, Any]] = None,
) -> MealPlanSummary:
    meals = [meal for day in days for meal in day.meals]
    tier_counts = {"normal": 0, "relaxed": 0, "emergency": 0}
    for meal in meals:
        tier_counts[meal.tier] = tier_counts.get(meal.tier, 0) + 1

    expected_meals_per_day = (
        request.temporary_overrides.meals_per_day
        or request.meals_per_day
        or 3
    )
    expected = max(1, int(request.days or 7)) * max(1, int(expected_meals_per_day))
    return MealPlanSummary(
        generated_meals=len(meals),
        empty_slots=max(0, expected - len(meals)),
        normal=tier_counts.get("normal", 0),
        relaxed=tier_counts.get("relaxed", 0),
        emergency=tier_counts.get("emergency", 0),
        avg_calorie_error=_average_macro_error(days, "calories", macro_targets),
        avg_protein_error=_average_macro_error(days, "protein", macro_targets),
        avg_fat_error=_average_macro_error(days, "fat", macro_targets),
        avg_carbs_error=_average_macro_error(days, "carbs", macro_targets),
    )


def _build_plan_progress(plan_id: str, days: List[MealPlanDay]) -> PlanProgress:
    all_meals = [meal for day in days for meal in day.meals]
    completed = [
        meal for meal in all_meals
        if meal.progress.checked or meal.progress.status in {"eaten", "skipped"}
    ]
    completed_ids = {meal.meal_id for meal in completed}
    completed_days = 0
    for day in days:
        if day.meals and all(meal.meal_id in completed_ids for meal in day.meals):
            completed_days += 1

    total = len(all_meals)
    return PlanProgress(
        plan_id=plan_id,
        days_total=len(days),
        days_completed=completed_days,
        meals_total=total,
        meals_completed=len(completed),
        completion_percent=round((len(completed) / total * 100.0) if total else 0.0, 1),
        current_day=min(len(days), completed_days + 1) if days else 1,
    )


def _request_from_row(row: MealPlan) -> GenerateMealPlanRequest:
    try:
        return GenerateMealPlanRequest.model_validate_json(row.request_json)
    except Exception:
        try:
            return GenerateMealPlanRequest.model_validate(json.loads(row.request_json or "{}"))
        except Exception:
            return GenerateMealPlanRequest()


def _find_meal_location(response: MealPlanResponse, meal_id: str) -> Optional[tuple[int, int]]:
    for day_index, day in enumerate(response.days):
        for meal_index, meal in enumerate(day.meals):
            if meal.meal_id == meal_id:
                return day_index, meal_index
    return None


def _pick_replacement(
    current_meal: MealPlanMeal,
    suggestions: List[MealPlanMeal],
    allow_same: bool = False,
) -> Optional[MealPlanMeal]:
    if not suggestions:
        return None
    for meal in suggestions:
        if meal.recipe.id != current_meal.recipe.id and meal.name != current_meal.name:
            return meal.model_copy(deep=True)
    return suggestions[0].model_copy(deep=True) if allow_same else None


def _meal_type_to_english(value: str) -> str:
    raw = str(value or "").lower()
    mapping = {
        "завтрак": "breakfast",
        "breakfast": "breakfast",
        "обед": "lunch",
        "lunch": "lunch",
        "ужин": "dinner",
        "dinner": "dinner",
        "перекус": "snack",
        "snack": "snack",
    }
    return mapping.get(raw, "dinner")


def _recalculate_day(day: MealPlanDay) -> None:
    calories = sum(meal.nutrition_for_user.calories for meal in day.meals)
    protein = sum(meal.nutrition_for_user.protein for meal in day.meals)
    fat = sum(meal.nutrition_for_user.fat for meal in day.meals)
    carbs = sum(meal.nutrition_for_user.carbs for meal in day.meals)
    day.macro_summary = MealNutrition(
        calories=round(calories, 1),
        protein=round(protein, 1),
        fat=round(fat, 1),
        carbs=round(carbs, 1),
    )
    day.actual_calories = day.macro_summary.calories
    day.score = round(
        sum(meal.score for meal in day.meals) / len(day.meals),
        4,
    ) if day.meals else 0.0


def _build_user_profile(user: User, request: GenerateMealPlanRequest) -> UserProfile:
    overrides = request.temporary_overrides
    goal = overrides.goal or request.goal or _goal_from_diet_type(user.diet_type)
    calories = overrides.target_calories or request.target_calories or user.daily_calories or 2000
    meals_per_day = overrides.meals_per_day or request.meals_per_day or user.meals_per_day or 3

    allergies = (
        overrides.allergies
        or overrides.allergens
        or _split_csv(user.allergens)
    )
    preferred = (
        overrides.preferred
        or overrides.preferred_ingredients
        or _split_csv(user.favorite_products)
    )
    excluded = (
        overrides.excluded
        or overrides.excluded_ingredients
        or _split_csv(user.excluded_products)
    )
    disliked = (
        overrides.disliked
        or overrides.disliked_ingredients
        or _split_csv(getattr(user, "disliked_products", ""))
    )

    return UserProfile(
        age=user.age or 25,
        sex=user.gender or "male",
        height_cm=user.height or 175,
        weight_kg=user.weight or 70.0,
        activity_level=getattr(user, "activity_level", None) or "moderate",
        allergies=expand_food_terms(allergies),
        preferred_ingredients=expand_food_terms(preferred),
        disliked_ingredients=expand_food_terms(disliked),
        excluded_ingredients=expand_food_terms(excluded),
        goal=goal,
        target_calories=int(calories),
        meals_per_day=int(meals_per_day),
    )


def _apply_request_to_user(user: User, request: GenerateMealPlanRequest) -> None:
    overrides = request.temporary_overrides
    if overrides.target_calories or request.target_calories:
        user.daily_calories = int(overrides.target_calories or request.target_calories)
    if overrides.goal or request.goal:
        user.diet_type = _diet_type_from_goal(str(overrides.goal or request.goal))
    if overrides.meals_per_day or request.meals_per_day:
        user.meals_per_day = int(overrides.meals_per_day or request.meals_per_day)
    allergies = overrides.allergies or overrides.allergens
    preferred = overrides.preferred or overrides.preferred_ingredients
    disliked = overrides.disliked or overrides.disliked_ingredients
    excluded = overrides.excluded or overrides.excluded_ingredients
    if allergies:
        user.allergens = ",".join(allergies)
    if preferred:
        user.favorite_products = ",".join(preferred)
    if disliked:
        user.disliked_products = ",".join(disliked)
    if excluded:
        user.excluded_products = ",".join(excluded)


def _profile_dict(user: User) -> Dict[str, Any]:
    return {
        "target_calories": user.daily_calories or 2000,
        "daily_calories": user.daily_calories or 2000,
        "goal": _goal_from_diet_type(user.diet_type),
        "diet_type": user.diet_type or "normal",
        "meals_per_day": user.meals_per_day or 3,
        "allergies": _split_csv(user.allergens),
        "excluded": _split_csv(user.excluded_products),
        "preferred": _split_csv(user.favorite_products),
        "disliked": _split_csv(getattr(user, "disliked_products", "")),
    }


def _profile_warnings(user: User) -> List[str]:
    missing = []
    if not user.age:
        missing.append("age")
    if not user.height:
        missing.append("height")
    if not user.weight:
        missing.append("weight")
    if not missing:
        return []
    return [
        "PROFILE_INCOMPLETE: missing "
        + ", ".join(missing)
        + "; safe defaults were used"
    ]


async def _get_plan_row(db: AsyncSession, user_email: str, plan_id: str) -> MealPlan:
    result = await db.execute(
        select(MealPlan).where(
            MealPlan.id == plan_id,
            MealPlan.user_email == user_email,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise _plan_not_found()
    return row


def _plan_not_found() -> HTTPException:
    return HTTPException(
        404,
        {"error": {"code": "PLAN_NOT_FOUND", "message": "Plan not found"}},
    )


def _average_macro_error(
    days: List[MealPlanDay],
    key: str,
    macro_targets: Optional[Dict[str, Any]] = None,
) -> float:
    errors = []
    for day in days:
        target = (
            day.target_calories
            if key == "calories"
            else _macro_target(day, key, macro_targets)
        )
        actual = getattr(day.macro_summary, key)
        if target > 0:
            errors.append(abs(actual - target) / target)
    return round(sum(errors) / len(errors), 4) if errors else 0.0


def _macro_target(
    day: MealPlanDay,
    key: str,
    macro_targets: Optional[Dict[str, Any]] = None,
) -> float:
    target_key = {
        "protein": "protein_g",
        "fat": "fat_g",
        "carbs": "carbs_g",
    }.get(key, key)

    if macro_targets and target_key in macro_targets:
        try:
            return float(macro_targets[target_key] or 0.0)
        except Exception:
            pass

    calories = day.target_calories
    if key == "protein":
        return calories * 0.24 / 4
    if key == "fat":
        return calories * 0.27 / 9
    if key == "carbs":
        return calories * 0.49 / 4
    return calories


def _slot_index_for_meal_type(planner: Any, meal_type: str, meals_per_day: int) -> int:
    for index in range(meals_per_day):
        if planner._meal_type_for_slot(index, meals_per_day) == meal_type:
            return index
    return max(0, meals_per_day - 1)


def _nutrition(raw: Dict[str, Any]) -> MealNutrition:
    return MealNutrition(
        calories=_float(raw.get("calories")),
        protein=_float(raw.get("protein")),
        fat=_float(raw.get("fat")),
        carbs=_float(raw.get("carbs")),
    )


def nutrition_for_user_dict(meal: Dict[str, Any]) -> Dict[str, Any]:
    raw = meal.get("nutrition", {}) or {}
    return raw if isinstance(raw, dict) else {}


def _scale_nutrition(nutrition: MealNutrition, factor: float) -> MealNutrition:
    return MealNutrition(
        calories=round(nutrition.calories * factor, 1),
        protein=round(nutrition.protein * factor, 1),
        fat=round(nutrition.fat * factor, 1),
        carbs=round(nutrition.carbs * factor, 1),
    )


def _scale_ingredients(ingredients: List[Any], factor: int) -> List[Any]:
    result = []
    for ingredient in ingredients:
        if isinstance(ingredient, dict):
            item = deepcopy(ingredient)
            for key in ("grams", "amount", "quantity"):
                if isinstance(item.get(key), (int, float)):
                    item[key] = round(float(item[key]) * factor, 1)
            result.append(item)
        else:
            result.append(ingredient)
    return result


def _instructions(value: Any) -> List[str]:
    return [localize_instruction(item) for item in parse_instruction_lines(value)]


def _image_url(meal: Dict[str, Any]) -> Optional[str]:
    for key in ("image_url", "image", "photo_url", "thumbnail_url", "image_path"):
        value = meal.get(key)
        if value:
            return str(value)
    recipe = meal.get("recipe")
    if isinstance(recipe, dict):
        for key in ("image_url", "image", "photo_url", "thumbnail_url", "image_path"):
            value = recipe.get(key)
            if value:
                return str(value)
    return None


def _localize_response(response: MealPlanResponse) -> MealPlanResponse:
    for day in response.days:
        for meal in day.meals:
            meal.name = localize_title(meal.name)
            meal.meal_type = localize_meal_type(meal.meal_type)
            if meal.main_carb:
                meal.main_carb = localize_food_name(meal.main_carb)
            meal.main_proteins = [
                localize_food_name(item) for item in meal.main_proteins
            ]
            meal.recipe.name = localize_title(meal.recipe.name)
            meal.recipe.ingredients = localize_ingredients(meal.recipe.ingredients)
            meal.recipe.ingredients_detail = localize_ingredients(
                meal.recipe.ingredients_detail
            )
            meal.recipe.instructions = _instructions(meal.recipe.instructions)
            if "scaled_ingredients" in meal.recipe.scaling:
                meal.recipe.scaling["scaled_ingredients"] = localize_ingredients(
                    meal.recipe.scaling.get("scaled_ingredients") or []
                )
    return response


def _stable_recipe_id(name: str) -> str:
    return name.lower().strip().replace(" ", "-")[:80] or uuid.uuid4().hex


def _goal_from_diet_type(value: Optional[str]) -> str:
    raw = str(value or "normal").lower()
    if raw in {"cut", "weight_loss"}:
        return "weight_loss"
    if raw in {"bulk", "muscle_gain"}:
        return "muscle_gain"
    return "balanced"


def _diet_type_from_goal(goal: str) -> str:
    raw = str(goal or "balanced").lower()
    if raw == "weight_loss":
        return "cut"
    if raw == "muscle_gain":
        return "bulk"
    return "normal"


def _split_csv(value: Optional[str]) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _list_of_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _float(value: Any) -> float:
    try:
        return round(float(value or 0.0), 1)
    except Exception:
        return 0.0


def _round(value: Any) -> float:
    try:
        return round(float(value or 0.0), 4)
    except Exception:
        return 0.0


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
