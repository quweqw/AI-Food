from typing import List


class PreferenceScorer:

    def score(self, ingredients, user_profile):
        """
        Score от 0 до 1
        """

        if not ingredients:
            return 0.0

        score = 0.5  # базовый

        ingredients = [i.lower() for i in ingredients]

        # ==============================
        # + за любимые продукты
        # ==============================
        for ing in ingredients:
            if ing in user_profile.preferred_ingredients:
                score += 0.15

        # ==============================
        # - за нелюбимые
        # ==============================
        for ing in ingredients:
            if ing in user_profile.disliked_ingredients:
                score -= 0.25

        # ==============================
        # - за повторяемость (слабый штраф)
        # ==============================
        recent = user_profile.get_recent_ingredients()

        overlap = len(set(ingredients) & recent)
        score -= overlap * 0.05

        # clamp
        return max(0.0, min(score, 1.0))