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
        ingredients_set = {i.lower() for i in ingredients}

        issues = []
        warnings = []

        allergies = {i.lower() for i in getattr(user_profile, "allergies", [])}
        excluded = {i.lower() for i in getattr(user_profile, "excluded_ingredients", [])}

        for ing in ingredients_set:
            if ing in excluded:
                issues.append(f"excluded ingredient: {ing}")

            if ing in allergies:
                issues.append(f"direct allergy: {ing}")

        for ing in ingredients_set:
            group = self.allergen_map.get(ing)
            if group and group.lower() in allergies:
                issues.append(f"allergen group: {group} (from {ing})")

        goal = getattr(user_profile, "goal", "balanced")

        if goal in ("weight_loss", "cut", "sushka", "сушка"):
            if "oil" in ingredients_set or "butter" in ingredients_set or "cream" in ingredients_set:
                warnings.append("higher fat content for cutting phase")

        if goal in ("muscle_gain", "bulk", "massonabor", "массонабор"):
            if not any(p in ingredients_set for p in ["chicken", "egg", "fish", "shrimp", "beef", "tofu"]):
                warnings.append("low protein density for mass gain")

        return {
            "is_safe": len(issues) == 0,
            "issues": issues,
            "warnings": warnings
        }