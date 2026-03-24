from typing import List


class DiversityEngine:
    def __init__(self):
        # Сколько последних блюд учитывать
        self.history_window = 5

    def score(self, ingredients: List[str], user_profile) -> float:
        """
        Оценивает разнообразие питания:
        - штрафует повторяющиеся блюда
        - штрафует повторяющиеся ингредиенты

        Возвращает score от 0 до 1
        """

        if not hasattr(user_profile, "recent_meals"):
            return 1.0

        recent_meals = user_profile.recent_meals[-self.history_window:]

        if not recent_meals:
            return 1.0

        score = 1.0
        ingredients_set = {i.lower() for i in ingredients}

        # ==============================
        # 1. EXACT MEAL REPEAT
        # ==============================
        current_signature = " ".join(sorted(ingredients_set))

        for meal in recent_meals:
            if isinstance(meal, dict):
                past_ingredients = set(meal.get("ingredients", []))
                past_signature = " ".join(sorted(past_ingredients))
            else:
                # если строка
                past_signature = str(meal).lower()

            if current_signature == past_signature:
                score -= 0.4

        # ==============================
        # 2. INGREDIENT OVERLAP
        # ==============================
        overlap_penalty = 0.0

        for meal in recent_meals:
            if isinstance(meal, dict):
                past_ingredients = set(meal.get("ingredients", []))
            else:
                continue

            overlap = len(ingredients_set & past_ingredients)

            if overlap > 0:
                overlap_penalty += 0.1 * overlap

        score -= overlap_penalty

        # ==============================
        # CLAMP
        # ==============================
        return max(0.0, min(score, 1.0))