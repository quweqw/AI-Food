# ranking_engine.py
from typing import Optional

# Ранжирование рецептов
class RankingEngine:
    def __init__(self):
        # Веса компонентов (можно изменять коэф. под задачу)
        # Сумма должна быть ≈ 1.0
        
        self.weights = {
            "preference": 0.5,
            "diversity": 0.3,
            "nutrition": 0.2
        }

    # Комбирование нескольких баллов в один итоговый (Значения в пределах от 0 до 1)
    def combine(
        self,
        pref_score: Optional[float] = None,
        diversity_score: Optional[float] = None,
        nutrition_score: Optional[float] = None
    ) -> float:

        scores = {
            "preference": pref_score,
            "diversity": diversity_score,
            "nutrition": nutrition_score
        }

        total_score = 0.0
        total_weight = 0.0

        for key, value in scores.items():
            if value is None:
                continue

            weight = self.weights.get(key, 0.0)

            total_score += value * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        final_score = total_score / total_weight

        return self._clamp(final_score)

    # ==============================
    # Оценка питания
    # ==============================
    
    # Простая оценка БЖУ под цели
    def score_nutrition(self, nutrition: dict, goal: str = "balanced") -> float:

        if not nutrition:
            return 0.5  # нейтрально

        calories = nutrition.get("calories", 0)
        protein = nutrition.get("protein", 0)
        fat = nutrition.get("fat", 0)
        carbs = nutrition.get("carbs", 0)

        score = 1.0

        if goal == "weight_loss":
            if calories > 700:
                score -= 0.4
            if fat > 25:
                score -= 0.2
            if protein > 20:
                score += 0.2

        elif goal == "fitness":
            if protein < 20:
                score -= 0.3
            else:
                score += 0.3

        elif goal == "mass_gain":
            if calories < 500:
                score -= 0.3
            if carbs > 50:
                score += 0.2

        # нормализация
        return self._clamp(score)

    # ==============================
    # Внутренее ранжирование
    # ==============================
    def _clamp(self, value: float) -> float:
        return max(0.0, min(value, 1.0))