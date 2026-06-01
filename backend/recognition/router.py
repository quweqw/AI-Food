from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from auth.service import decode_token
import tempfile
import shutil
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from ai.core.user_profile import UserProfile
try:
    from food_terms import expand_food_terms
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from backend.food_terms import expand_food_terms
from meal_planner.localization import localize_food_name, localize_ingredients, localize_instruction, localize_title

router = APIRouter(prefix="/recognition", tags=["recognition"])
security = HTTPBearer()

_recognizer = None

def get_recognizer():
    global _recognizer
    if _recognizer is None:
        from ai.pipeline.food_recognizer import recognize_food
        _recognizer = recognize_food
    return _recognizer

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    email = decode_token(credentials.credentials)
    if not email:
        raise HTTPException(401, "Невалидный токен")
    return email

@router.post("/image")
async def recognize_image(
    file: UploadFile = File(...),
    age: int = Form(25),
    gender: str = Form("male"),
    height: int = Form(175),
    weight: float = Form(70.0),
    diet_type: str = Form("normal"),
    daily_calories: int = Form(2000),
    allergens: str = Form(""),
    excluded_products: str = Form(""),
    favorite_products: str = Form(""),
    disliked_products: str = Form(""),
    user_email: str = Depends(get_current_user)
):
    suffix = os.path.splitext(file.filename)[1] or ".jpg"

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix
    ) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        goal_map = {
            "bulk": "muscle_gain",
            "cut": "weight_loss",
            "normal": "balanced",
        }

        user_profile = UserProfile(
            age=age,
            sex=gender,
            height_cm=height,
            weight_kg=weight,
            activity_level="moderate",
            allergies=expand_food_terms([a.strip() for a in allergens.split(",") if a.strip()]),
            preferred_ingredients=expand_food_terms([p.strip() for p in favorite_products.split(",") if p.strip()]),
            disliked_ingredients=expand_food_terms([d.strip() for d in disliked_products.split(",") if d.strip()]),
            excluded_ingredients=expand_food_terms([e.strip() for e in excluded_products.split(",") if e.strip()]),
            goal=goal_map.get(diet_type, "balanced"),
            target_calories=daily_calories,
        )

        recognize_food = get_recognizer()
        result = recognize_food(tmp_path, user_profile=user_profile)

        if result is None:
            raise HTTPException(400, "Еда не найдена на фото")

        if result.get("status") == "unsafe":
            raise HTTPException(400, f"Небезопасные ингредиенты: {result.get('issues')}")

        return _localize_recognition_result(result)

    finally:
        os.unlink(tmp_path)


def _localize_recognition_result(result: dict) -> dict:
    localized = dict(result or {})
    localized["meal"] = localize_title(localized.get("meal") or "Блюдо")
    localized["ingredients"] = localize_ingredients(localized.get("ingredients") or [])
    localized["nutrition_basis"] = "per_100g_estimate"

    recipe = localized.get("recipe")
    if isinstance(recipe, dict):
        recipe = dict(recipe)
        if recipe.get("dish_name"):
            recipe["dish_name"] = localize_title(recipe["dish_name"])
        if recipe.get("name"):
            recipe["name"] = localize_title(recipe["name"])
        if isinstance(recipe.get("ingredients"), list):
            recipe["ingredients"] = localize_ingredients(recipe["ingredients"])
        steps = recipe.get("steps") or recipe.get("instructions")
        if isinstance(steps, list):
            recipe["steps"] = [localize_instruction(str(step)) for step in steps]
            recipe["instructions"] = recipe["steps"]
        if recipe.get("tips"):
            recipe["tips"] = localize_instruction(str(recipe["tips"]))
        localized["recipe"] = recipe

    substitutions = localized.get("substitutions")
    if isinstance(substitutions, list):
        localized["substitutions"] = [
            {
                **item,
                "from": localize_food_name(item.get("from")),
                "to": localize_food_name(item.get("to")),
            }
            if isinstance(item, dict)
            else item
            for item in substitutions
        ]

    return localized
