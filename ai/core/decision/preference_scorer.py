from __future__ import annotations

from typing import Any, Iterable, List, Set, Union, Dict


Ingredient = Union[str, Dict[str, Any]]


class PreferenceScorer:
    """
    Оценка предпочтений пользователя.

    Поддерживает:
    - list[str]
    - list[dict] вида {"name": "rice", "grams": 180, "state": "cooked"}

    На вход желательно передавать ingredient_names из MealPlanner,
    но модуль не упадёт, если получит dict-ингредиенты.
    """

    def score(self, ingredients: List[Ingredient], user_profile) -> float:
        ingredient_names = self._normalize_ingredients(ingredients)

        if not ingredient_names:
            return 0.0

        preferred = self._profile_set(user_profile, "preferred_ingredients")
        disliked = self._profile_set(user_profile, "disliked_ingredients")
        excluded = self._profile_set(user_profile, "excluded_ingredients")
        recent = self._recent_ingredients(user_profile)

        score = 0.5

        ingredient_set = set(ingredient_names)

        # Любимые продукты: мягкий бонус.
        preferred_hits = len(ingredient_set & preferred)
        score += min(0.30, preferred_hits * 0.12)

        # Нелюбимые: сильнее, чем бонус за любимые.
        disliked_hits = len(ingredient_set & disliked)
        score -= min(0.50, disliked_hits * 0.22)

        # Исключённые не должны проходить SafetyChecker, но на всякий случай штрафуем.
        excluded_hits = len(ingredient_set & excluded)
        score -= min(0.70, excluded_hits * 0.35)

        # Повторяемость по истории: мягкий штраф.
        overlap = len(ingredient_set & recent)
        score -= min(0.30, overlap * 0.04)

        return round(max(0.0, min(score, 1.0)), 3)

    # ==============================
    # HELPERS
    # ==============================

    def _ingredient_name(self, item: Ingredient) -> str:
        if isinstance(item, dict):
            return self._normalize_name(item.get("name", ""))
        return self._normalize_name(item)

    def _normalize_ingredients(self, ingredients: Iterable[Ingredient]) -> List[str]:
        result: List[str] = []

        for item in ingredients or []:
            name = self._ingredient_name(item)
            if name:
                result.append(name)

        return result

    def _normalize_name(self, value: Any) -> str:
        value = str(value or "").strip().lower()
        value = value.replace("-", "_")
        value = "_".join(value.split())
        return value

    def _profile_set(self, user_profile, attr: str) -> Set[str]:
        values = getattr(user_profile, attr, []) or []
        return {self._normalize_name(v) for v in values if self._normalize_name(v)}

    def _recent_ingredients(self, user_profile) -> Set[str]:
        if hasattr(user_profile, "get_recent_ingredients"):
            try:
                return {
                    self._normalize_name(v)
                    for v in user_profile.get_recent_ingredients()
                    if self._normalize_name(v)
                }
            except Exception:
                pass

        recent_meals = getattr(user_profile, "recent_meals", []) or []
        result: Set[str] = set()

        for meal in recent_meals:
            if not isinstance(meal, dict):
                continue

            for item in meal.get("ingredients", []) or []:
                name = self._ingredient_name(item)
                if name:
                    result.add(name)

        return result
