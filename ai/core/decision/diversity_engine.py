from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Union


logger = logging.getLogger("DiversityEngine")
Ingredient = Union[str, Dict[str, Any]]


class DiversityEngine:
    """
    Оценка разнообразия рациона.

    Поддерживает:
    - list[str]
    - list[dict] вида {"name": "chicken", "grams": 150, "state": "cooked"}

    Логика:
    - сильный штраф за полный повтор блюда;
    - мягкий штраф за повтор ингредиентов;
    - отдельный штраф за повтор подкатегории белка;
    - лёгкий штраф за повтор категорий.
    """

    def __init__(self, food_groups_path: Union[str, Path, None] = None, history_window: int = 5):
        self.history_window = history_window
        self.food_groups = self._load_food_groups(food_groups_path)

    # ==============================
    # PUBLIC
    # ==============================

    def score(self, ingredients: List[Ingredient], user_profile) -> float:
        current = set(self._normalize_ingredients(ingredients))

        if not current:
            return 0.0

        recent_meals = getattr(user_profile, "recent_meals", []) or []
        recent = recent_meals[-self.history_window:]

        if not recent:
            return 1.0

        current_categories = self._categories_for(current)
        current_subcategories = self._subcategories_for(current)

        score = 1.0

        for meal in recent:
            past = set(self._normalize_ingredients(meal.get("ingredients", [])))

            if not past:
                continue

            past_categories = self._categories_for(past)
            past_subcategories = self._subcategories_for(past)

            # Полный повтор блюда.
            if current == past:
                score -= 0.60
                continue

            # Пересечение конкретных ингредиентов.
            ingredient_overlap = len(current & past)
            score -= min(0.30, ingredient_overlap * 0.04)

            # Jaccard similarity: защищает от очень похожих блюд.
            union_size = max(len(current | past), 1)
            jaccard = len(current & past) / union_size
            score -= min(0.20, jaccard * 0.18)

            # Повтор protein subcategory: например lean_meat снова lean_meat.
            current_protein_subcats = {
                subcat
                for subcat in current_subcategories
                if subcat and subcat != "unknown"
                and self._subcategory_belongs_to_category(subcat, current, "protein")
            }

            past_protein_subcats = {
                subcat
                for subcat in past_subcategories
                if subcat and subcat != "unknown"
                and self._subcategory_belongs_to_category(subcat, past, "protein")
            }

            protein_subcat_overlap = len(current_protein_subcats & past_protein_subcats)
            score -= min(0.25, protein_subcat_overlap * 0.12)

            # Лёгкий штраф за повтор категорий, кроме unknown.
            category_overlap = (current_categories & past_categories) - {"unknown"}
            score -= min(0.15, len(category_overlap) * 0.025)

        return round(max(0.0, min(1.0, score)), 3)

    # ==============================
    # FOOD GROUPS
    # ==============================

    def _load_food_groups(self, explicit_path: Union[str, Path, None]) -> dict:
        candidate_paths: List[Path] = []

        if explicit_path:
            candidate_paths.append(Path(explicit_path))

        here = Path(__file__).resolve().parent

        candidate_paths.extend([
            here / "food_groups.json",
            here / "data" / "food_groups.json",
            here.parent / "data" / "food_groups.json",
            here.parent.parent / "data" / "food_groups.json",
            here.parent.parent.parent / "data" / "food_groups.json",
        ])

        for path in candidate_paths:
            try:
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception as exc:
                logger.warning(f"Failed to load food_groups.json from {path}: {exc}")

        logger.warning("food_groups.json not found; DiversityEngine will use ingredient-level diversity only.")
        return {}

    def _group_info(self, ingredient: str) -> dict:
        ingredient = self._normalize_name(ingredient)

        info = self.food_groups.get(ingredient)
        if isinstance(info, dict):
            return info

        # fallback: spaces/underscore
        alt = ingredient.replace("_", " ")
        info = self.food_groups.get(alt)
        if isinstance(info, dict):
            return info

        return {}

    def _category(self, ingredient: str) -> str:
        return str(self._group_info(ingredient).get("category", "unknown")).lower()

    def _subcategory(self, ingredient: str) -> str:
        return str(self._group_info(ingredient).get("subcategory", "unknown")).lower()

    def _categories_for(self, ingredients: Iterable[str]) -> Set[str]:
        return {self._category(i) for i in ingredients}

    def _subcategories_for(self, ingredients: Iterable[str]) -> Set[str]:
        return {self._subcategory(i) for i in ingredients}

    def _subcategory_belongs_to_category(
        self,
        subcategory: str,
        ingredients: Iterable[str],
        category: str,
    ) -> bool:
        for ingredient in ingredients:
            if self._subcategory(ingredient) == subcategory and self._category(ingredient) == category:
                return True
        return False

    # ==============================
    # NORMALIZATION
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
