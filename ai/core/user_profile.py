from typing import List


class UserProfile:
    def __init__(
        self,
        allergies=None,
        preferred_ingredients=None,
        disliked_ingredients=None,
        excluded_ingredients=None,
        goal=None,
        recent_meals=None,
        allow_substitutions=True,
        target_calories=None,
        meals_per_day=3,
        activity_level="moderate",
        age=None,
        sex=None,
        height_cm=None,
        weight_kg=None
    ):
        self.allergies = allergies or []
        self.preferred_ingredients = preferred_ingredients or []
        self.disliked_ingredients = disliked_ingredients or []
        self.excluded_ingredients = excluded_ingredients or []

        self.goal = goal
        self.allow_substitutions = allow_substitutions
        self.recent_meals = recent_meals or []

        self.target_calories = target_calories
        self.meals_per_day = meals_per_day
        self.activity_level = activity_level
        self.age = age
        self.sex = sex
        self.height_cm = height_cm
        self.weight_kg = weight_kg

    # ==============================
    # HISTORY MANAGEMENT
    # ==============================

    def add_meal(self, ingredients: List[str]):
        self.recent_meals.append({
            "ingredients": [i.lower() for i in ingredients]
        })

        # ограничиваем историю
        if len(self.recent_meals) > 20:
            self.recent_meals.pop(0)

    def get_recent_ingredients(self):
        result = set()

        for meal in self.recent_meals:
            result.update(meal["ingredients"])

        return result
