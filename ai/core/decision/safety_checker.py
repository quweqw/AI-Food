from typing import List, Dict


class SafetyChecker:
    def __init__(self):
        # Базовая карта аллергенов (можешь расширять)
        self.allergen_map = {
            "shrimp": "shellfish",
            "crab": "shellfish",
            "lobster": "shellfish",
            "peanut": "peanut",
            "milk": "dairy",
            "cheese": "dairy",
            "butter": "dairy",
            "yogurt": "dairy",
            "egg": "egg",
            "eggs": "egg",
            "pork": "pork",
            "beef": "red_meat",
            "soy": "soy",
            "tofu": "soy",
            "wheat": "gluten",
            "bread": "gluten",
            "noodles": "gluten"
        }

    def check(self, ingredients: List[str], user_profile) -> Dict:
        """
        Проверяет:
        - прямые аллергии
        - аллергенные группы
        - исключённые ингредиенты

        Возвращает:
        {
            "is_safe": bool,
            "issues": [str],
            "warnings": [str]
        }
        """

        ingredients_set = {i.lower() for i in ingredients}

        issues = []
        warnings = []

        # ==============================
        # 1. EXCLUDED INGREDIENTS
        # ==============================
        for ing in ingredients_set:
            if ing in user_profile.excluded_ingredients:
                issues.append(f"excluded ingredient: {ing}")

        # ==============================
        # 2. DIRECT ALLERGIES
        # ==============================
        for ing in ingredients_set:
            if ing in user_profile.allergies:
                issues.append(f"allergy: {ing}")

        # ==============================
        # 3. ALLERGEN GROUPS
        # ==============================
        for ing in ingredients_set:
            group = self.allergen_map.get(ing)

            if group and group in user_profile.allergies:
                issues.append(f"allergen group: {group} (from {ing})")

        # ==============================
        # 4. DIET WARNINGS (soft rules)
        # ==============================
        goal = getattr(user_profile, "goal", "balanced")

        if goal == "weight_loss":
            if "oil" in ingredients_set or "butter" in ingredients_set:
                warnings.append("high fat ingredients for weight loss")

        if goal == "fitness":
            if not any(p in ingredients_set for p in ["chicken", "egg", "fish", "shrimp"]):
                warnings.append("low protein meal")

        # ==============================
        # FINAL RESULT
        # ==============================
        return {
            "is_safe": len(issues) == 0,
            "issues": issues,
            "warnings": warnings
        }