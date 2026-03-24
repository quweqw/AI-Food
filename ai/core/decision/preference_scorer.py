from typing import List


class PreferenceScorer:
    def __init__(self):
        # Веса (можешь тюнить)
        self.preferred_weight = 0.3
        self.penalty_weight = 0.4

    def score(self, ingredients: List[str], user_profile) -> float:
        """
        Оценивает соответствие предпочтениям пользователя

        Возвращает score от 0 до 1
        """

        if not ingredients:
            return 0.0

        ingredients_set = {i.lower() for i in ingredients}

        preferred = set(getattr(user_profile, "preferred_ingredients", []))
        excluded = set(getattr(user_profile, "excluded_ingredients", []))

        score = 1.0

        # ==============================
        # 1. PREFERRED INGREDIENTS BONUS
        # ==============================
        if preferred:
            match_count = len(ingredients_set & preferred)
            bonus = (match_count / len(preferred)) * self.preferred_weight
            score += bonus

        # ==============================
        # 2. EXCLUDED INGREDIENTS PENALTY
        # ==============================
        if excluded:
            bad_count = len(ingredients_set & excluded)
            penalty = bad_count * self.penalty_weight
            score -= penalty

        # ==============================
        # 3. GOAL-BASED SCORING
        # ==============================
        goal = getattr(user_profile, "goal", "balanced")

        # Простейшая эвристика
        if goal == "fitness":
            if any(p in ingredients_set for p in ["chicken", "egg", "fish", "shrimp"]):
                score += 0.2

        elif goal == "weight_loss":
            if any(f in ingredients_set for f in ["fried", "oil", "butter"]):
                score -= 0.2

        elif goal == "mass_gain":
            if any(c in ingredients_set for c in ["rice", "pasta", "noodles", "bread"]):
                score += 0.2

        # ==============================
        # NORMALIZE
        # ==============================
        return max(0.0, min(score, 1.0))