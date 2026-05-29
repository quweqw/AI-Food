"""
AI Food smoke tests.

Как запускать:
1. Положи этот файл рядом с meal_planner.py / nutrition_engine.py / portion_optimizer.py.
2. Убедись, что рядом или в нужной data-папке лежат:
   - nutrition_db.json
   - portion_rules.json
   - food_groups.json
   - category_rules.json
   - satiety_rules.json
3. Запусти:
   python test_ai_food_pipeline.py

Цель:
- проверить cooked -> raw пересчёт;
- проверить PortionOptimizer;
- проверить полный MealPlanner pipeline.
"""
from __future__ import annotations
from pprint import pprint


from ai.llm.nutrition_engine import NutritionEngine
from ai.core.meal_planner import MealPlanner

from ai.core.decision.portion_optimizer import PortionOptimizer
from ai.core.decision.safety_checker import SafetyChecker
from ai.core.decision.preference_scorer import PreferenceScorer
from ai.core.decision.diversity_engine import DiversityEngine
from ai.core.decision.substitution_engine import SubstitutionEngine


class FakeUserProfile:
    def __init__(self):
        self.goal = "balanced"
        self.meals_per_day = 3
        self.target_calories = 2000

        self.age = 25
        self.sex = "male"
        self.height_cm = 185
        self.weight_kg = 70
        self.activity_level = "moderate"

        self.protein_target_g = 110
        self.fat_target_g = 65
        self.carb_limit_g = None

        self.allergies = []
        self.preferred_ingredients = ["chicken", "rice"]
        self.disliked_ingredients = []
        self.excluded_ingredients = []
        self.recent_meals = []

    def add_meal(self, ingredients):
        self.recent_meals.append({
            "ingredients": [str(i).lower() for i in ingredients]
        })
        if len(self.recent_meals) > 20:
            self.recent_meals.pop(0)

    def get_recent_ingredients(self):
        result = set()
        for meal in self.recent_meals:
            result.update(meal.get("ingredients", []))
        return result


class FakeRecipeSearch:
    def search(self, query, top_k=80):
        return [
            {
                "name": "Chicken Rice Bowl",
                "ingredients": [
                    {"name": "chicken", "grams": 150, "state": "cooked"},
                    {"name": "rice", "grams": 180, "state": "cooked"},
                ],
                "score": 0.95,
                "cuisine": "generic",
                "servings": 1,
            },
            {
                "name": "Beef Rice Bowl",
                "ingredients": [
                    {"name": "beef", "grams": 150, "state": "cooked"},
                    {"name": "rice", "grams": 180, "state": "cooked"},
                ],
                "score": 0.80,
                "cuisine": "generic",
                "servings": 1,
            },
            {
                "name": "Egg Rice Bowl",
                "ingredients": [
                    {"name": "egg", "grams": 100, "state": "raw"},
                    {"name": "rice", "grams": 180, "state": "cooked"},
                ],
                "score": 0.75,
                "cuisine": "generic",
                "servings": 1,
            },
        ]


def approx(value, target, tolerance):
    return abs(value - target) <= tolerance


def test_1_nutrition_engine_cooked_raw():
    print("\n=== TEST 1: NutritionEngine cooked -> raw ===")

    engine = NutritionEngine()

    result = engine.calculate([
        {"name": "rice", "grams": 250, "state": "cooked"}
    ])

    pprint(result)

    rice_entry = engine.db.get("rice", {})
    rice_nutrition = rice_entry.get("nutrition_per_100g", rice_entry)

    rice_state = rice_entry.get("state", "raw")
    rice_factor = float(rice_entry.get("cooked_weight_factor", 1.0))

    calories = result.get("calories", 0)
    eaten_weight = result.get("eaten_weight_g", 0)
    nutrition_weight = result.get("nutrition_weight_g", 0)

    expected_nutrition_weight = 250.0

    if rice_state == "raw":
        expected_nutrition_weight = 250.0 / rice_factor

    expected_calories = (
        float(rice_nutrition.get("calories", 0))
        * expected_nutrition_weight
        / 100.0
    )

    assert approx(eaten_weight, 250, 1), (
        f"eaten_weight_g должен быть около 250, got {eaten_weight}"
    )

    assert approx(nutrition_weight, expected_nutrition_weight, 3), (
        f"nutrition_weight_g должен быть около {expected_nutrition_weight:.1f}, "
        f"got {nutrition_weight}"
    )

    assert approx(calories, expected_calories, 8), (
        f"calories должны быть около {expected_calories:.1f}, got {calories}"
    )

    if calories < 250:
        raise AssertionError(
            "Калории rice слишком низкие. Вероятно, в nutrition_db.json rice указан как raw, "
            "но значения взяты для cooked rice. Для raw rice должно быть около 350-370 kcal / 100g."
        )

    print("OK: cooked rice пересчитался в raw-equivalent корректно.")


def test_2_portion_optimizer():
    print("\n=== TEST 2: PortionOptimizer ===")

    engine = NutritionEngine()
    optimizer = PortionOptimizer(engine)
    profile = FakeUserProfile()

    recipe = {
        "name": "Chicken Rice Bowl",
        "ingredients": [
            {"name": "chicken", "grams": 150, "state": "cooked"},
            {"name": "rice", "grams": 180, "state": "cooked"},
        ],
        "servings": 1,
    }

    optimized = optimizer.optimize_recipe(
        recipe=recipe,
        user_profile=profile,
        meal_type="lunch",
        slot_target_calories=800,
        slot_macro_targets={
            "protein_g": 44,
            "fat_g": 26,
            "carbs_g": 90,
        },
    )

    pprint(optimized)

    assert optimized["ingredients"], "optimizer не вернул ingredients"
    assert optimized["nutrition"].get("calories", 0) > 0, "optimizer вернул 0 calories"
    assert optimized["portion"]["score"] >= 0, "portion score некорректный"

    print("OK: PortionOptimizer вернул оптимизированную порцию.")


def test_3_meal_planner_full_day():
    print("\n=== TEST 3: MealPlanner full day ===")

    engine = NutritionEngine()
    optimizer = PortionOptimizer(engine)
    profile = FakeUserProfile()

    planner = MealPlanner(
        recipe_search=FakeRecipeSearch(),
        nutrition_engine=engine,
        safety_checker=SafetyChecker() if SafetyChecker else None,
        preference_scorer=PreferenceScorer() if PreferenceScorer else None,
        diversity_engine=DiversityEngine() if DiversityEngine else None,
        substitution_engine=None,
        portion_optimizer=optimizer,
        llm=None,
    )

    plan = planner.build_plan(
        user_profile=profile,
        days=1,
        candidate_limit=10,
        explain_with_llm=False,
    )

    pprint(plan)

    assert plan["status"] == "ok", f"status должен быть ok, got {plan.get('status')}"
    assert len(plan["plan"]) == 1, "должен быть 1 день"
    assert len(plan["plan"][0]["meals"]) > 0, "не выбрано ни одного блюда"

    day_total = plan["plan"][0]["day_total"]

    assert day_total.get("calories", 0) > 0, "day calories = 0"
    assert day_total.get("protein", 0) > 0, "day protein = 0"

    print("OK: MealPlanner собрал день.")


if __name__ == "__main__":
    test_1_nutrition_engine_cooked_raw()
    test_2_portion_optimizer()
    test_3_meal_planner_full_day()

    print("\nALL TESTS PASSED")
