from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set, Union


Ingredient = Union[str, Dict[str, Any]]


class SafetyChecker:
    """
    Проверка безопасности ингредиентов.

    Поддерживает:
    - list[str]
    - list[dict] вида {"name": "milk", "grams": 200, "state": "cooked"}

    Важно:
    - Этот модуль НЕ считает КБЖУ.
    - Он работает только с именами ингредиентов.
    - Allergy/excluded группы тоже учитываются: dairy, gluten, shellfish и т.д.
    """

    def __init__(self):
        self.allergen_map = {
            "shrimp": "shellfish",
            "prawn": "shellfish",
            "crab": "shellfish",
            "lobster": "shellfish",

            "peanut": "peanut",
            "peanuts": "peanut",

            "milk": "dairy",
            "cheese": "dairy",
            "butter": "dairy",
            "yogurt": "dairy",
            "cream": "dairy",
            "cottage_cheese": "dairy",

            "egg": "egg",
            "eggs": "egg",

            "pork": "pork",
            "beef": "red_meat",
            "lamb": "red_meat",

            "soy": "soy",
            "tofu": "soy",
            "soy_milk": "soy",

            "wheat": "gluten",
            "bread": "gluten",
            "noodles": "gluten",
            "pasta": "gluten",
            "flour": "gluten",
        }

        self.high_fat_warning_ingredients = {
            "oil",
            "olive_oil",
            "butter",
            "cream",
            "margarine",
            "coconut_oil",
            "avocado_oil",
            "shortening",
        }

        self.protein_sources = {
            "chicken",
            "turkey",
            "egg",
            "eggs",
            "fish",
            "salmon",
            "tuna",
            "shrimp",
            "beef",
            "pork",
            "tofu",
            "cottage_cheese",
            "yogurt",
        }

    # ==============================
    # PUBLIC
    # ==============================

    def check(self, ingredients: List[Ingredient], user_profile) -> Dict[str, Any]:
        ingredient_names = self._normalize_ingredients(ingredients)
        ingredients_set = set(ingredient_names)

        issues: List[str] = []
        warnings: List[str] = []

        allergies = self._profile_set(user_profile, "allergies")
        excluded = self._profile_set(user_profile, "excluded_ingredients")

        for ing in sorted(ingredients_set):
            group = self.allergen_map.get(ing)

            # Прямое исключение продукта
            if ing in excluded:
                issues.append(f"excluded ingredient: {ing}")

            # Исключение по группе, например excluded=["dairy"]
            if group and group in excluded:
                issues.append(f"excluded group: {group} (from {ing})")

            # Прямая аллергия на продукт
            if ing in allergies:
                issues.append(f"direct allergy: {ing}")

            # Аллергия на группу, например allergies=["gluten"]
            if group and group in allergies:
                issues.append(f"allergen group: {group} (from {ing})")

        goal = str(getattr(user_profile, "goal", "balanced") or "balanced").lower()

        if goal in ("weight_loss", "cut", "sushka", "сушка", "diet"):
            if ingredients_set & self.high_fat_warning_ingredients:
                warnings.append("higher fat ingredient for weight-loss phase")

        if goal in ("muscle_gain", "bulk", "mass_gain", "massonabor", "массонабор"):
            if not (ingredients_set & self.protein_sources):
                warnings.append("low obvious protein-source density for muscle gain")

        # Убираем дубли, сохраняя стабильный порядок
        issues = list(dict.fromkeys(issues))
        warnings = list(dict.fromkeys(warnings))

        return {
            "is_safe": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "checked_ingredients": ingredient_names,
        }

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
