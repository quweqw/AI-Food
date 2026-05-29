from __future__ import annotations
from pprint import pprint
from types import SimpleNamespace

from ai.core.meal_planner import MealPlanner
from ai.llm.nutrition_engine import NutritionEngine
from ai.recipes.recipe_search import RecipeSearch

import os


def print_recipe_row(planner: MealPlanner, idx: int, recipe: dict) -> None:
    ingredients = recipe.get("ingredients", [])
    main_carb = planner._detect_main_carb(ingredients)

    print(
        f"{idx:02d}. "
        f"score={float(recipe.get('score', 0.0)):.4f} "
        f"rerank={float(recipe.get('rerank_score', recipe.get('score', 0.0))):.4f} "
        f"main_carb={main_carb} | {recipe.get('name')}"
    )
    print("    ingredients:", ingredients)

    if recipe.get("rerank_components"):
        print("    rerank_components:")
        pprint(recipe["rerank_components"], width=120)


def main():

    CANDIDATE_LIMIT = 80
    MAX_OPTIMIZED_PER_SLOT = 12
    PORTION_MAX_CANDIDATES = 360

    os.environ.setdefault("AI_FOOD_MAX_OPTIMIZED_PER_SLOT", str(MAX_OPTIMIZED_PER_SLOT))
    os.environ.setdefault("AI_FOOD_PORTION_CACHE", "1")
    os.environ.setdefault("AI_FOOD_PORTION_MAX_CANDIDATES", str(PORTION_MAX_CANDIDATES))

    recipe_search = RecipeSearch()
    nutrition_engine = NutritionEngine()

    planner = MealPlanner(
        recipe_search=recipe_search,
        nutrition_engine=nutrition_engine,
    )

    profile = SimpleNamespace(
        goal="balanced",
        target_calories=2000,
        meals_per_day=3,

        age=25,
        sex="male",
        height_cm=175,
        weight_kg=75,
        activity_level="moderate",

        preferred_ingredients=[],
        disliked_ingredients=[],
        excluded_ingredients=[],
        allergies=[],
        recent_meals=[],

        protein_target_g=None,
        fat_target_g=None,
        carb_limit_g=None,
    )

    goal = planner._normalize_goal(profile.goal)
    target_calories = planner._get_target_calories(profile, goal)
    macro_targets = planner._get_macro_targets(target_calories, goal, profile)
    meals_per_day = planner._clamp_meals_per_day(profile.meals_per_day)
    weights = planner._meal_weights(meals_per_day, goal)

    used_main_carbs = []

    print("\n=== DEBUG MEALPLANNER SLOTS ===")
    print("goal:", goal)
    print("target_calories:", target_calories)
    print("meals_per_day:", meals_per_day)
    print("macro_targets:")
    pprint(macro_targets, width=120)

    print("\nmeal_planner_rules loaded:")
    print("schema_version:", planner.meal_planner_rules.get("schema_version"))
    print("main_carb_groups:", list(planner.meal_planner_rules.get("main_carb_groups", {}).keys()))
    print("main_carb_repeat_policy:")
    pprint(planner.meal_planner_rules.get("main_carb_repeat_policy", {}), width=120)

    for slot_idx in range(meals_per_day):
        meal_type = planner._meal_type_for_slot(slot_idx, meals_per_day)
        slot_target_calories = target_calories * weights[slot_idx]
        slot_target_macros = planner._slot_macro_targets(macro_targets, weights[slot_idx])

        query = planner._build_slot_search_query(
            user_profile=profile,
            goal=goal,
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            slot_target_macros=slot_target_macros,
            used_main_carbs=used_main_carbs,
        )

        candidates = planner._fetch_slot_candidates(
            user_profile=profile,
            goal=goal,
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            slot_target_macros=slot_target_macros,
            candidate_limit=CANDIDATE_LIMIT,
            used_main_carbs=used_main_carbs,
        )

        print("\n" + "=" * 80)
        print(f"SLOT {slot_idx + 1}: {meal_type}")
        print("=" * 80)
        print("query:", query)
        print("slot_target_calories:", round(slot_target_calories, 1))
        print("slot_target_macros:")
        pprint(slot_target_macros, width=120)
        print("used_main_carbs before slot:", used_main_carbs)
        print("candidates:", len(candidates))

        for idx, recipe in enumerate(candidates[:15], start=1):
            print_recipe_row(planner, idx, recipe)

        # Симуляция выбора первого кандидата, чтобы проверить,
        # меняется ли query и применяется ли логика variety на следующем слоте.
        if candidates:
            first_recipe = candidates[0]
            first_carb = planner._detect_main_carb(first_recipe.get("ingredients", []))
            if first_carb:
                used_main_carbs.append(first_carb)

        print("used_main_carbs after simulation:", used_main_carbs)

    print("#####################################")
    print(f"CANDIDATE_LIMIT: {CANDIDATE_LIMIT}")
    print(f"MAX_OPTIMIZED_PER_SLOT: {MAX_OPTIMIZED_PER_SLOT}")
    print(f"PORTION_MAX_CANDIDATES: {PORTION_MAX_CANDIDATES}")
    print("\n=== DEBUG DONE ===")
    

if __name__ == "__main__":
    main()