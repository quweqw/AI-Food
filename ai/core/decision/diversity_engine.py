from typing import List


class DiversityEngine:
    def __init__(self):
        # Сколько последних блюд учитывать
        self.history_window = 5

    def score(self, ingredients, user_profile):
        if not hasattr(user_profile, "recent_meals"):
            return 1.0

        recent = user_profile.recent_meals[-self.history_window:]

        if not recent:
            return 1.0

        score = 1.0
        ingredients_set = set(ingredients)

        # ==============================
        # ЖЁСТКИЙ штраф за повтор блюда
        # ==============================
        current = set(ingredients)

        for meal in recent:
            past = set(meal.get("ingredients", []))

            if current == past:
                score -= 0.5

        # ==============================
        # мягкий штраф за пересечение
        # ==============================
        for meal in recent:
            past = set(meal.get("ingredients", []))
            overlap = len(current & past)

            score -= overlap * 0.08

        return max(0.0, min(score, 1.0))