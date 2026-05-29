from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union


logger = logging.getLogger("SubstitutionEngine")
Ingredient = Union[str, Dict[str, Any]]


class SubstitutionEngine:
    """
    Система замен ингредиентов.

    Поддерживает:
    - list[str]
    - list[dict] вида {"name": "milk", "grams": 200, "state": "raw"}

    Главная правка:
    при замене сохраняются grams/state/amount, чтобы MealPlanner и NutritionEngine
    не теряли граммовки.
    """

    def __init__(
        self,
        data_path: Optional[Union[str, Path]] = None,
        allow_substitution_for_allergies: bool = True,
        strict_allergy: bool = True,
    ):
        self.ALLOW_SUBSTITUTION_FOR_ALLERGIES = allow_substitution_for_allergies
        self.strict_allergy = strict_allergy

        self.data_path = self._resolve_data_path(data_path)
        self.substitutions = self._load_data()

    # ==============================
    # PUBLIC
    # ==============================

    def apply(
        self,
        ingredients: List[Ingredient],
        user_profile,
        cuisine: Optional[str] = None,
    ) -> Dict[str, Any]:
        new_ingredients: List[Ingredient] = []
        replacements: List[dict] = []
        removed: List[dict] = []

        allergies = self._profile_set(user_profile, "allergies")
        disliked = self._profile_set(user_profile, "disliked_ingredients")
        excluded = self._profile_set(user_profile, "excluded_ingredients")
        dietary_preferences = self._profile_set(user_profile, "dietary_preferences")
        dietary_restrictions = self._profile_set(user_profile, "dietary_restrictions")

        goal = self._normalize_name(getattr(user_profile, "goal", "balanced"))

        context = {
            "goal": goal,
            "cuisine": self._normalize_name(cuisine),
            "restrictions": {
                "allergies": allergies,
                "disliked": disliked,
                "excluded": excluded,
                "dietary_preferences": dietary_preferences,
                "dietary_restrictions": dietary_restrictions,
            },
        }

        for original in ingredients or []:
            name = self._ingredient_name(original)

            if not name:
                continue

            reason = self._replacement_reason(
                name=name,
                allergies=allergies,
                disliked=disliked,
                excluded=excluded,
            )

            if reason is None:
                new_ingredients.append(original)
                continue

            # Excluded продукт нельзя оставлять. Пытаемся заменить, иначе удаляем.
            if reason == "excluded":
                substitute = self._get_best_substitute(name, context)
                if substitute:
                    new_ingredients.append(self._replace_ingredient(original, substitute))
                    replacements.append({
                        "from": name,
                        "to": substitute,
                        "reason": "excluded",
                    })
                else:
                    removed.append({
                        "ingredient": name,
                        "reason": "excluded_no_substitute",
                    })
                continue

            # Allergy: если разрешены замены — заменяем; если нет или замены нет — удаляем.
            if reason == "allergy":
                if not self.ALLOW_SUBSTITUTION_FOR_ALLERGIES:
                    removed.append({
                        "ingredient": name,
                        "reason": "allergy_substitution_disabled",
                    })
                    continue

                substitute = self._get_best_substitute(name, context)
                if substitute:
                    new_ingredients.append(self._replace_ingredient(original, substitute))
                    replacements.append({
                        "from": name,
                        "to": substitute,
                        "reason": "allergy",
                    })
                else:
                    if self.strict_allergy:
                        removed.append({
                            "ingredient": name,
                            "reason": "allergy_no_substitute",
                        })
                    else:
                        new_ingredients.append(original)
                continue

            # Disliked: если замена есть — заменяем, если нет — оставляем.
            if reason == "disliked":
                substitute = self._get_best_substitute(name, context)
                if substitute:
                    new_ingredients.append(self._replace_ingredient(original, substitute))
                    replacements.append({
                        "from": name,
                        "to": substitute,
                        "reason": "disliked",
                    })
                else:
                    new_ingredients.append(original)
                continue

            new_ingredients.append(original)

        return {
            "ingredients": new_ingredients,
            "replacements": replacements,
            "removed": removed,
        }

    # ==============================
    # LOADING
    # ==============================

    def _resolve_data_path(self, explicit_path: Optional[Union[str, Path]]) -> Optional[Path]:
        if explicit_path:
            path = Path(explicit_path)
            if path.exists():
                return path

        here = Path(__file__).resolve().parent

        candidates = [
            here / "substitutions.json",
            here / "data" / "substitutions.json",
            here.parent / "data" / "substitutions.json",
            here.parent.parent / "data" / "substitutions.json",
            here.parent.parent.parent / "data" / "substitutions.json",
        ]

        for path in candidates:
            if path.exists():
                return path

        return candidates[0]

    def _load_data(self) -> dict:
        if self.data_path is None or not self.data_path.exists():
            logger.warning(f"Substitution file not found: {self.data_path}")
            return {}

        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning(f"Failed to load substitutions from {self.data_path}: {exc}")
            return {}

        return data if isinstance(data, dict) else {}

    # ==============================
    # SUBSTITUTION LOGIC
    # ==============================

    def _replacement_reason(
        self,
        name: str,
        allergies: Set[str],
        disliked: Set[str],
        excluded: Set[str],
    ) -> Optional[str]:
        if name in excluded:
            return "excluded"

        if name in allergies:
            return "allergy"

        if name in disliked:
            return "disliked"

        return None

    def _get_best_substitute(self, ingredient: str, context: dict) -> Optional[str]:
        ingredient = self._normalize_name(ingredient)

        candidates = self.substitutions.get(ingredient, [])

        # fallback для старых JSON, где ключи могут быть с пробелами
        if not candidates:
            candidates = self.substitutions.get(ingredient.replace("_", " "), [])

        if not isinstance(candidates, list) or not candidates:
            return None

        scored: List[Tuple[str, float]] = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            item = self._normalize_name(candidate.get("item", ""))
            if not item:
                continue

            score = self._score_candidate(candidate, context)

            if score <= -999:
                continue

            scored.append((item, score))

        if not scored:
            return None

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def _score_candidate(self, candidate: dict, context: dict) -> float:
        item = self._normalize_name(candidate.get("item", ""))
        tags = {self._normalize_name(t) for t in candidate.get("tags", []) or []}
        cuisines = {self._normalize_name(c) for c in candidate.get("cuisine", []) or []}

        restrictions = context.get("restrictions", {})
        allergies = restrictions.get("allergies", set())
        disliked = restrictions.get("disliked", set())
        excluded = restrictions.get("excluded", set())
        dietary_preferences = restrictions.get("dietary_preferences", set())
        dietary_restrictions = restrictions.get("dietary_restrictions", set())

        # Не предлагаем то, что явно запрещено.
        if item in allergies or item in excluded:
            return -999.0

        # Если tags пересекаются с аллергенами/исключениями — тоже нельзя.
        if tags & allergies:
            return -999.0

        if tags & excluded:
            return -999.0

        score = float(candidate.get("base_score", 0.5))

        cuisine = context.get("cuisine")
        if cuisine:
            if "any" in cuisines:
                score += 0.08
            elif cuisine in cuisines:
                score += 0.25
            elif cuisines:
                score -= 0.08

        goal = context.get("goal")

        if goal in ("muscle_gain", "bulk", "mass_gain", "massonabor", "массонабор"):
            if tags & {"high_protein", "meat", "animal", "protein"}:
                score += 0.20
            if tags & {"low_protein"}:
                score -= 0.15

        if goal in ("weight_loss", "cut", "diet", "sushka", "сушка"):
            if tags & {"low_calorie", "low_fat", "high_fiber"}:
                score += 0.18
            if tags & {"high_fat", "energy_dense"}:
                score -= 0.12

        if item in disliked:
            score -= 0.35

        # Диетические ограничения: vegan, dairy_free и т.д.
        all_diet_restrictions = dietary_preferences | dietary_restrictions

        if "vegan" in all_diet_restrictions:
            if "vegan" in tags:
                score += 0.20
            else:
                score -= 0.45

        if "dairy_free" in all_diet_restrictions or "dairy-free" in all_diet_restrictions:
            if "dairy_free" in tags or "dairy-free" in tags:
                score += 0.15
            if "dairy" in tags:
                score -= 0.50

        if "gluten_free" in all_diet_restrictions or "gluten-free" in all_diet_restrictions:
            if "gluten_free" in tags or "gluten-free" in tags:
                score += 0.15
            if "gluten" in tags:
                score -= 0.50

        return score

    # ==============================
    # INGREDIENT TRANSFORM
    # ==============================

    def _replace_ingredient(self, original: Ingredient, substitute_name: str) -> Ingredient:
        substitute_name = self._normalize_name(substitute_name)

        if isinstance(original, dict):
            updated = dict(original)
            updated["name"] = substitute_name
            return updated

        return substitute_name

    # ==============================
    # COMPAT HELPERS
    # ==============================

    def _should_replace(self, ingredient: str, user_profile) -> bool:
        name = self._normalize_name(ingredient)
        allergies = self._profile_set(user_profile, "allergies")
        disliked = self._profile_set(user_profile, "disliked_ingredients")
        excluded = self._profile_set(user_profile, "excluded_ingredients")

        return name in allergies or name in disliked or name in excluded

    def _get_reason(self, ingredient: str, user_profile) -> str:
        name = self._normalize_name(ingredient)
        allergies = self._profile_set(user_profile, "allergies")
        disliked = self._profile_set(user_profile, "disliked_ingredients")
        excluded = self._profile_set(user_profile, "excluded_ingredients")

        if name in excluded:
            return "excluded"
        if name in allergies:
            return "allergy"
        if name in disliked:
            return "disliked"
        return "replacement"

    # ==============================
    # NORMALIZATION
    # ==============================

    def _ingredient_name(self, item: Ingredient) -> str:
        if isinstance(item, dict):
            return self._normalize_name(item.get("name", ""))
        return self._normalize_name(item)

    def _normalize_name(self, value: Any) -> str:
        value = str(value or "").strip().lower()
        value = value.replace("-", "_")
        value = "_".join(value.split())
        return value

    def _profile_set(self, user_profile, attr: str) -> Set[str]:
        values = getattr(user_profile, attr, []) or []
        return {self._normalize_name(v) for v in values if self._normalize_name(v)}
