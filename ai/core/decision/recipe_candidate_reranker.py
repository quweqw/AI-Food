from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class RecipeCandidateReranker:
    """
    Reranker рецептов после FAISS/embeddings.

    FAISS хорошо ищет похожий текст, но плохо понимает:
    - это полноценный приём пищи или десерт;
    - есть ли белок;
    - подходит ли блюдо под meal planning;
    - есть ли нормальные категории продуктов.

    Этот слой исправляет выдачу до MealPlanner scoring.
    """

    DESSERT_NAME_KEYWORDS = {
        "cake", "cookies", "cookie", "brownie", "brownies", "pancake", "pancakes",
        "crepe", "crepes", "mochi", "pryaniki", "medovik", "trdelnik",
        "chocolate", "mousse", "pie", "banana_bread", "sweet", "dessert",
        "chak_chak", "glaze"
    }

    DESSERT_INGREDIENTS = {
        "sugar", "brown_sugar", "white_sugar", "powdered_sugar",
        "honey", "maple_syrup", "syrup", "glaze", "chocolate",
        "chocolate_chips", "dark_chocolate", "vanilla", "nutella",
        "jam", "ice_cream", "sweetened_condensed_milk"
    }

    WEAK_MEAL_INGREDIENTS = {
        "flour", "baking_powder", "baking_soda", "cornstarch",
        "glaze", "sugar", "honey", "maple_syrup"
    }

    PROTEIN_HINTS = {
        "chicken", "chicken_breast", "chicken_breasts", "chicken_thighs",
        "whole_chicken", "cooked_chicken_breast", "shredded_chicken",
        "beef", "ground_beef", "beef_sirloin", "flank_steak", "beef_chuck",
        "pork", "ground_pork", "salmon", "salmon_fillet", "tuna",
        "shrimp", "egg", "eggs", "tofu", "turkey", "lamb",
        "cottage_cheese", "yogurt"
    }

    CARB_HINTS = {
        "rice", "cooked_rice", "bomba_rice", "sushi_rice", "arborio_rice",
        "potato", "potatoes", "russet_potatoes", "mashed_potato",
        "pasta", "spaghetti", "fettuccine", "noodles", "egg_noodles",
        "rice_noodles", "bread", "tortilla", "tortilla_wraps",
        "burger_bun", "burger_buns", "oats", "buckwheat"
    }

    VEGETABLE_HINTS = {
        "carrot", "onion", "tomato", "cucumber", "broccoli", "asparagus",
        "spinach", "lettuce", "romaine_lettuce", "zucchini", "cabbage",
        "bell_pepper", "green_beans", "peas", "cauliflower", "mushrooms",
        "celery", "beets", "eggplant"
    }

    FAT_HINTS = {
        "olive_oil", "oil", "butter", "sesame_oil", "avocado",
        "nuts", "peanut_butter", "cream", "heavy_cream", "cheese"
    }

    def __init__(self, nutrition_engine=None):
        self.nutrition_engine = nutrition_engine

    def rerank(
        self,
        recipes: List[Dict[str, Any]],
        user_profile=None,
        limit: int = 80,
    ) -> List[Dict[str, Any]]:
        scored = []

        for recipe in recipes:
            if not isinstance(recipe, dict):
                continue

            score_data = self.score_recipe(recipe, user_profile=user_profile)

            recipe_copy = dict(recipe)
            recipe_copy["rerank_score"] = score_data["score"]
            recipe_copy["rerank_components"] = score_data["components"]

            scored.append(recipe_copy)

        scored.sort(
            key=lambda r: (
                r.get("rerank_score", 0.0),
                r.get("score", 0.0),
            ),
            reverse=True,
        )

        return scored[:limit]

    def score_recipe(self, recipe: Dict[str, Any], user_profile=None) -> Dict[str, Any]:
        name = self._normalize(recipe.get("name") or recipe.get("title") or recipe.get("dish_name") or "")
        ingredients = self._ingredient_names(recipe.get("ingredients", []))

        retrieval = clamp(float(recipe.get("score", 0.5) or 0.5))

        dessert_penalty = self._dessert_penalty(name, ingredients)
        protein_score = self._presence_score(ingredients, self.PROTEIN_HINTS)
        carb_score = self._presence_score(ingredients, self.CARB_HINTS)
        vegetable_score = self._presence_score(ingredients, self.VEGETABLE_HINTS)
        fat_score = self._presence_score(ingredients, self.FAT_HINTS)

        meal_structure = clamp(
            0.42 * protein_score
            + 0.26 * carb_score
            + 0.22 * vegetable_score
            + 0.10 * fat_score
        )

        db_coverage = self._db_coverage_score(ingredients)
        preference = self._preference_score(ingredients, user_profile)
        restriction_penalty = self._restriction_penalty(ingredients, user_profile)
        weak_meal_penalty = self._weak_meal_penalty(ingredients)

        starch_flour_penalty = self._starch_flour_penalty(ingredients)
        rich_fat_penalty = self._rich_fat_penalty(ingredients)
        true_main_protein = self._true_main_protein_score(ingredients)
        real_vegetable_score = self._real_vegetable_score(ingredients)

        meal_structure = clamp(
            0.45 * true_main_protein
            + 0.25 * carb_score
            + 0.20 * real_vegetable_score
            + 0.10 * fat_score
        )

        final = (
            0.24 * retrieval
            + 0.32 * meal_structure
            + 0.18 * true_main_protein
            + 0.10 * real_vegetable_score
            + 0.08 * db_coverage
            + 0.08 * preference
            - 0.35 * dessert_penalty
            - 0.22 * weak_meal_penalty
            - 0.22 * starch_flour_penalty
            - 0.16 * rich_fat_penalty
            - 0.50 * restriction_penalty
        )

        final = clamp(final)

        return {
            "score": final,
            "components": {
                "retrieval": round(retrieval, 3),
                "meal_structure": round(meal_structure, 3),
                "protein_score": round(protein_score, 3),
                "carb_score": round(carb_score, 3),
                "vegetable_score": round(vegetable_score, 3),
                "fat_score": round(fat_score, 3),
                "db_coverage": round(db_coverage, 3),
                "preference": round(preference, 3),
                "dessert_penalty": round(dessert_penalty, 3),
                "weak_meal_penalty": round(weak_meal_penalty, 3),
                "restriction_penalty": round(restriction_penalty, 3),
                "true_main_protein": round(true_main_protein, 3),
                "real_vegetable_score": round(real_vegetable_score, 3),
                "starch_flour_penalty": round(starch_flour_penalty, 3),
                "rich_fat_penalty": round(rich_fat_penalty, 3),
            },
        }

    def _dessert_penalty(self, name: str, ingredients: List[str]) -> float:
        penalty = 0.0

        name_tokens = set(name.split("_"))
        if name_tokens & self.DESSERT_NAME_KEYWORDS:
            penalty += 0.8

        dessert_hits = len(set(ingredients) & self.DESSERT_INGREDIENTS)
        penalty += min(0.8, dessert_hits * 0.18)

        # flour + sugar + butter почти всегда выпечка/десерт
        ing_set = set(ingredients)
        if {"flour", "sugar", "butter"}.issubset(ing_set):
            penalty += 0.45

        return clamp(penalty)

    def _weak_meal_penalty(self, ingredients: List[str]) -> float:
        ing_set = set(ingredients)

        weak_hits = len(ing_set & self.WEAK_MEAL_INGREDIENTS)
        protein = self._presence_score(ingredients, self.PROTEIN_HINTS)

        penalty = min(0.6, weak_hits * 0.12)

        if protein < 0.3:
            penalty += 0.25

        return clamp(penalty)

    def _true_main_protein_score(self, ingredients: List[str]) -> float:
        """
        Отличает полноценный белковый продукт от случайного яйца/сыра в тесте.
        """

        ing_set = set(ingredients)

        strong_proteins = {
            "chicken", "chicken_breast", "chicken_breasts", "chicken_thighs",
            "whole_chicken", "cooked_chicken_breast", "shredded_chicken",
            "beef", "ground_beef", "beef_sirloin", "flank_steak", "beef_chuck",
            "pork", "ground_pork", "salmon", "salmon_fillet", "tuna",
            "shrimp", "lamb", "tofu", "turkey", "canned_fish"
        }

        medium_proteins = {
            "egg", "eggs", "cheese", "cottage_cheese", "yogurt",
            "beans", "kidney_beans", "black_beans", "chickpeas"
        }

        strong_hits = 0
        medium_hits = 0

        for ing in ing_set:
            for p in strong_proteins:
                if p in ing or ing in p:
                    strong_hits += 1
                    break

            for p in medium_proteins:
                if p in ing or ing in p:
                    medium_hits += 1
                    break

        score = strong_hits * 0.75 + medium_hits * 0.25

        return clamp(score)


    def _real_vegetable_score(self, ingredients: List[str]) -> float:
        """
        Onion/garlic/herbs не считаем полноценной овощной частью.
        """

        ing_set = set(ingredients)

        real_vegetables = {
            "broccoli", "asparagus", "spinach", "zucchini", "cabbage",
            "cauliflower", "green_beans", "peas", "bell_pepper",
            "tomato", "cucumber", "lettuce", "romaine_lettuce",
            "eggplant", "beets", "carrot", "mushrooms"
        }

        weak_aromatics = {
            "onion", "garlic", "green_onion", "shallots", "parsley",
            "dill", "cilantro", "thyme", "bay_leaf", "rosemary"
        }

        real_hits = 0
        aromatic_hits = 0

        for ing in ing_set:
            for v in real_vegetables:
                if v in ing or ing in v:
                    real_hits += 1
                    break

            if ing in weak_aromatics:
                aromatic_hits += 1

        score = real_hits * 0.45 + aromatic_hits * 0.06

        return clamp(score)


    def _starch_flour_penalty(self, ingredients: List[str]) -> float:
        """
        Штраф за блюда, где основа — тесто/мука/выпечка.
        Не убивает пасту/лапшу полностью, но снижает выпечку и мучные блюда.
        """

        ing_set = set(ingredients)

        flour_like = {
            "flour", "yeast_dough", "puff_pastry", "breadcrumbs",
            "panko_breadcrumbs", "baking_powder", "baking_soda",
            "cornstarch"
        }

        refined_starch = {
            "spaghetti", "fettuccine", "noodles", "egg_noodles",
            "lasagna_noodles", "rice_noodles", "small_pasta",
            "ditalini_pasta", "burger_bun", "burger_buns",
            "tortilla", "tortillas", "tortilla_wraps", "baguette"
        }

        flour_hits = len(ing_set & flour_like)
        refined_hits = len(ing_set & refined_starch)

        penalty = flour_hits * 0.18 + refined_hits * 0.08

        # flour + butter + sour cream/cheese = тяжёлое мучное блюдо
        if "flour" in ing_set and ("butter" in ing_set or "sour_cream" in ing_set or "cheese" in ing_set):
            penalty += 0.20

        return clamp(penalty)


    def _rich_fat_penalty(self, ingredients: List[str]) -> float:
        """
        Штраф за тяжёлые жирные ингредиенты.
        Olive oil / avocado не штрафуем так сильно.
        """

        ing_set = set(ingredients)

        rich_fats = {
            "butter", "heavy_cream", "cream", "sour_cream",
            "mayonnaise", "cheddar_cheese", "cheese", "bacon",
            "tail_fat_or_butter", "oil_for_frying"
        }

        moderate_fats = {
            "olive_oil", "sesame_oil", "avocado", "nuts", "peanut_butter"
        }

        penalty = len(ing_set & rich_fats) * 0.12
        penalty += len(ing_set & moderate_fats) * 0.04

        return clamp(penalty)

    def _presence_score(self, ingredients: List[str], hints: Set[str]) -> float:
        if not ingredients:
            return 0.0

        hits = 0

        for ing in ingredients:
            if ing in hints:
                hits += 1
                continue

            # Поддержка chicken_breast, salmon_fillet, russet_potatoes и т.д.
            for hint in hints:
                if hint in ing or ing in hint:
                    hits += 1
                    break

        return clamp(hits / 2.0)

    def _db_coverage_score(self, ingredients: List[str]) -> float:
        if not ingredients or self.nutrition_engine is None:
            return 0.5

        ok = 0

        for ing in ingredients:
            try:
                canonical, entry = self.nutrition_engine._lookup(ing)
                if entry is not None:
                    ok += 1
            except Exception:
                pass

        return clamp(ok / max(len(ingredients), 1))

    def _preference_score(self, ingredients: List[str], user_profile) -> float:
        if user_profile is None:
            return 0.5

        preferred = {
            self._normalize(i)
            for i in getattr(user_profile, "preferred_ingredients", []) or []
        }

        disliked = {
            self._normalize(i)
            for i in getattr(user_profile, "disliked_ingredients", []) or []
        }

        if not preferred and not disliked:
            return 0.5

        ing_set = set(ingredients)

        score = 0.5
        score += min(0.3, len(ing_set & preferred) * 0.12)
        score -= min(0.4, len(ing_set & disliked) * 0.20)

        return clamp(score)

    def _restriction_penalty(self, ingredients: List[str], user_profile) -> float:
        if user_profile is None:
            return 0.0

        excluded = {
            self._normalize(i)
            for i in getattr(user_profile, "excluded_ingredients", []) or []
        }

        allergies = {
            self._normalize(i)
            for i in getattr(user_profile, "allergies", []) or []
        }

        blocked = excluded | allergies
        if not blocked:
            return 0.0

        hits = len(set(ingredients) & blocked)
        return clamp(hits * 0.5)

    def _ingredient_names(self, ingredients: Any) -> List[str]:
        if not isinstance(ingredients, list):
            return []

        result = []

        for item in ingredients:
            if isinstance(item, str):
                name = self._normalize(item)
            elif isinstance(item, dict):
                name = self._normalize(item.get("name", ""))
            else:
                name = ""

            if name:
                result.append(name)

        return result

    def _normalize(self, value: Any) -> str:
        value = str(value or "").strip().lower()
        value = value.replace("-", "_")
        value = "_".join(value.split())
        return value