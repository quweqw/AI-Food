
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

logger = logging.getLogger("PortionOptimizer")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "ai" / "data"

Ingredient = Union[str, Dict[str, Any]]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


class PortionOptimizer:
    """
    PROD portion optimizer.

    Задача:
    - взять рецепт с ingredients / source.ingredients_detail;
    - восстановить граммовки на 1 порцию;
    - подобрать масштаб порций под calorie/macros target;
    - вернуть структуру, совместимую с MealPlanner._score_candidate():

      {
        "ingredients": [...],
        "nutrition": {...},
        "portion": {
          "score": float,
          "components": {...},
          ...
        }
      }

    Важные принципы:
    - не делает LLM-вызовов;
    - использует NutritionEngine как единственный источник КБЖУ;
    - не делает старый тяжёлый перебор 4500+ вариантов;
    - имеет cache, потому что одни и те же рецепты часто проверяются повторно.
    """

    GOAL_ALIASES = {
        "cut": "weight_loss",
        "weight_loss": "weight_loss",
        "sushka": "weight_loss",
        "сушка": "weight_loss",
        "diet": "weight_loss",

        "bulk": "muscle_gain",
        "muscle_gain": "muscle_gain",
        "mass_gain": "muscle_gain",
        "massonabor": "muscle_gain",
        "массонабор": "muscle_gain",

        "balanced": "balanced",
        "ordinary": "balanced",
        "обычный": "balanced",
        "maintenance": "balanced",
    }

    MACRO_KEYS = ("protein_g", "fat_g", "carbs_g")

    # Эти роли не должны масштабироваться так же агрессивно, как курица/рис/овощи.
    LOW_SCALING_ROLES = {
        "seasoning",
        "spice",
        "herb",
        "salt",
        "sauce",
        "condiment",
        "sweetener",
        "liquid",
        "broth",
        "water",
    }

    DEFAULT_PORTION_RANGES = {
        "protein": (70.0, 170.0, 320.0),
        "carbs": (60.0, 180.0, 380.0),
        "fat": (3.0, 12.0, 35.0),
        "vegetable": (40.0, 120.0, 400.0),
        "fruit": (60.0, 140.0, 300.0),
        "dairy": (40.0, 120.0, 300.0),
        "sauce": (5.0, 25.0, 80.0),
        "seasoning": (0.5, 3.0, 15.0),
        "liquid": (20.0, 120.0, 600.0),
        "other": (20.0, 100.0, 300.0),
    }

    # Жёсткие sanity-лимиты на съедаемый вес одной порции.
    # Нужны, чтобы низкокалорийные супы/овощные блюда не раздувались
    # до 1.2–1.8 кг ради попадания в calorie target.
    HARD_EATEN_WEIGHT_LIMITS = {
        "breakfast": 720.0,
        "lunch": 950.0,
        "dinner": 900.0,
        "snack": 360.0,
        "snack2": 360.0,
    }

    SOUP_EATEN_WEIGHT_LIMITS = {
        "lunch": 820.0,
        "dinner": 780.0,
        "breakfast": 650.0,
        "snack": 360.0,
        "snack2": 360.0,
    }

    def __init__(
        self,
        nutrition_engine,
        data_dir: Optional[Union[str, Path]] = None,
        max_candidates: Optional[int] = None,
    ):
        self.nutrition_engine = nutrition_engine
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR

        self.portion_rules = self._load_json(self.data_dir / "portion_rules.json", {})
        self.food_groups = self._load_json(self.data_dir / "food_groups.json", {})
        self.category_rules = self._load_json(self.data_dir / "category_rules.json", {})
        self.food_aliases = self._load_json(self.data_dir / "food_aliases.json", {})

        self.group_lookup = self._build_group_lookup(self.food_groups)

        self.max_candidates = int(
            max_candidates
            if max_candidates is not None
            else os.getenv("AI_FOOD_PORTION_MAX_CANDIDATES", "360")
        )

        self.enable_cache = os.getenv("AI_FOOD_PORTION_CACHE", "1") != "0"
        self.cache_max_size = int(os.getenv("AI_FOOD_PORTION_CACHE_SIZE", "4096"))
        self._optimization_cache: Dict[str, Dict[str, Any]] = {}

    # ──────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────

    def optimize_recipe(
        self,
        recipe: Dict[str, Any],
        user_profile=None,
        meal_type: str = "lunch",
        slot_target_calories: Optional[float] = None,
        slot_macro_targets: Optional[Dict[str, float]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Cached wrapper.

        MealPlanner вызывает именно этот метод.
        """

        if not isinstance(recipe, dict):
            recipe = {"name": "unknown", "ingredients": []}

        meal_type = str(meal_type or "lunch").lower().strip()
        profile_dict = self._profile_as_dict(user_profile)

        if slot_target_calories is None:
            slot_target_calories = self._fallback_slot_calories(
                profile_dict=profile_dict,
                meal_type=meal_type,
            )

        slot_target_calories = max(1.0, float(slot_target_calories))

        if slot_macro_targets is None:
            slot_macro_targets = self._fallback_slot_macros(
                profile_dict=profile_dict,
                slot_target_calories=slot_target_calories,
            )

        slot_macro_targets = self._normalize_macro_targets(slot_macro_targets)

        if not self.enable_cache:
            return self._optimize_recipe_uncached(
                recipe=recipe,
                profile_dict=profile_dict,
                meal_type=meal_type,
                slot_target_calories=slot_target_calories,
                slot_macro_targets=slot_macro_targets,
            )

        cache_key = self._portion_cache_key(
            recipe=recipe,
            profile_dict=profile_dict,
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            slot_macro_targets=slot_macro_targets,
        )

        cached = self._optimization_cache.get(cache_key)
        if cached is not None:
            result = copy.deepcopy(cached)
            result.setdefault("portion", {})
            result["portion"]["cache_hit"] = True
            return result

        result = self._optimize_recipe_uncached(
            recipe=recipe,
            profile_dict=profile_dict,
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            slot_macro_targets=slot_macro_targets,
        )

        self._cache_set(cache_key, result)

        result = copy.deepcopy(result)
        result.setdefault("portion", {})
        result["portion"]["cache_hit"] = False
        return result

    # ──────────────────────────────────────────────
    # CORE OPTIMIZATION
    # ──────────────────────────────────────────────

    def _optimize_recipe_uncached(
        self,
        recipe: Dict[str, Any],
        profile_dict: Optional[Dict[str, Any]],
        meal_type: str,
        slot_target_calories: float,
        slot_macro_targets: Dict[str, float],
    ) -> Dict[str, Any]:
        goal = self._normalize_goal(self._profile_get(profile_dict, "goal", "balanced"))

        base_ingredients = self._extract_recipe_ingredients(
            recipe=recipe,
            profile_dict=profile_dict,
            meal_type=meal_type,
        )

        if not base_ingredients:
            return self._empty_result(
                reason="no_ingredients",
                slot_target_calories=slot_target_calories,
                slot_macro_targets=slot_macro_targets,
            )

        base_nutrition = self._calculate_nutrition(
            base_ingredients,
            profile_dict=profile_dict,
            meal_type=meal_type,
        )

        candidates = self._generate_candidate_portions(
            base_ingredients=base_ingredients,
            base_nutrition=base_nutrition,
            goal=goal,
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            slot_macro_targets=slot_macro_targets,
        )

        best: Optional[Dict[str, Any]] = None
        tested = 0

        for ingredients in candidates:
            tested += 1

            nutrition = self._calculate_nutrition(
                ingredients,
                profile_dict=profile_dict,
                meal_type=meal_type,
            )

            score_info = self._score_portion(
                ingredients=ingredients,
                nutrition=nutrition,
                base_ingredients=base_ingredients,
                goal=goal,
                meal_type=meal_type,
                slot_target_calories=slot_target_calories,
                slot_macro_targets=slot_macro_targets,
            )

            if best is None or score_info["score"] > best["portion"]["score"]:
                best = {
                    "ingredients": ingredients,
                    "nutrition": nutrition,
                    "portion": {
                        **score_info,
                        "target_calories": round(slot_target_calories, 1),
                        "target_macros": {
                            "protein_g": round(slot_macro_targets.get("protein_g", 0.0), 1),
                            "fat_g": round(slot_macro_targets.get("fat_g", 0.0), 1),
                            "carbs_g": round(slot_macro_targets.get("carbs_g", 0.0), 1),
                        },
                        "tested_candidates": tested,
                    },
                }

        if best is None:
            nutrition = base_nutrition
            score_info = self._score_portion(
                ingredients=base_ingredients,
                nutrition=nutrition,
                base_ingredients=base_ingredients,
                goal=goal,
                meal_type=meal_type,
                slot_target_calories=slot_target_calories,
                slot_macro_targets=slot_macro_targets,
            )
            best = {
                "ingredients": base_ingredients,
                "nutrition": nutrition,
                "portion": {
                    **score_info,
                    "target_calories": round(slot_target_calories, 1),
                    "target_macros": slot_macro_targets,
                    "tested_candidates": 1,
                },
            }

        best["portion"]["tested_candidates"] = tested
        best["portion"]["eaten_weight_g"] = round(
            float(best["nutrition"].get("eaten_weight_g", 0.0) or 0.0),
            1,
        )
        best["portion"]["nutrition_weight_g"] = round(
            float(best["nutrition"].get("nutrition_weight_g", 0.0) or 0.0),
            1,
        )
        best["portion"]["cache_hit"] = False

        return best

    # ──────────────────────────────────────────────
    # INGREDIENT EXTRACTION
    # ──────────────────────────────────────────────

    def _extract_recipe_ingredients(
        self,
        recipe: Dict[str, Any],
        profile_dict: Optional[Dict[str, Any]],
        meal_type: str,
    ) -> List[Dict[str, Any]]:
        """
        Приоритет:
        1. recipe["source"]["ingredients_detail"] — новая prod-структура recipes.json;
        2. recipe["ingredients_detail"];
        3. recipe["ingredients"].
        """

        source = recipe.get("source", {})
        if not isinstance(source, dict):
            source = {}

        servings = self._recipe_servings(recipe, source)

        detail = None
        if isinstance(source.get("ingredients_detail"), list):
            detail = source.get("ingredients_detail")
        elif isinstance(recipe.get("ingredients_detail"), list):
            detail = recipe.get("ingredients_detail")

        ingredients: List[Dict[str, Any]] = []

        if detail:
            for item in detail:
                if not isinstance(item, dict):
                    continue

                name = (
                    item.get("canonical_name")
                    or item.get("name")
                    or item.get("ingredient")
                    or item.get("item")
                )

                if not name:
                    continue

                grams = (
                    item.get("grams")
                    if item.get("grams") is not None
                    else item.get("weight_g", item.get("amount_g"))
                )

                grams = safe_float(grams, 0.0)
                grams = self._maybe_convert_recipe_grams_to_serving(
                    grams=grams,
                    item=item,
                    recipe=recipe,
                    source=source,
                    servings=servings,
                )

                normalized = self._complete_ingredient(
                    name=name,
                    grams=grams if grams > 0 else None,
                    state=item.get("state") or item.get("input_state"),
                    role=item.get("role") or item.get("category"),
                    optional=bool(item.get("optional", False)),
                    profile_dict=profile_dict,
                    meal_type=meal_type,
                    amount_source=item.get("amount_source", "ingredients_detail"),
                )

                if normalized:
                    ingredients.append(normalized)

            if ingredients:
                return self._dedupe_ingredients(ingredients)

        raw_ingredients = recipe.get("ingredients", [])

        for item in raw_ingredients or []:
            if isinstance(item, str):
                name = item
                grams = None
                state = None
                role = None
                optional = False
                amount_source = "portion_rule"
            elif isinstance(item, dict):
                name = (
                    item.get("canonical_name")
                    or item.get("name")
                    or item.get("ingredient")
                    or item.get("item")
                )
                grams = item.get("grams", item.get("weight_g", item.get("amount")))
                state = item.get("state") or item.get("input_state")
                role = item.get("role") or item.get("category")
                optional = bool(item.get("optional", False))
                amount_source = item.get("amount_source", "recipe_ingredients")
            else:
                continue

            normalized = self._complete_ingredient(
                name=name,
                grams=grams,
                state=state,
                role=role,
                optional=optional,
                profile_dict=profile_dict,
                meal_type=meal_type,
                amount_source=amount_source,
            )

            if normalized:
                ingredients.append(normalized)

        return self._dedupe_ingredients(ingredients)

    def _complete_ingredient(
        self,
        name: Any,
        grams: Any,
        state: Any,
        role: Any,
        optional: bool,
        profile_dict: Optional[Dict[str, Any]],
        meal_type: str,
        amount_source: str,
    ) -> Optional[Dict[str, Any]]:
        canonical = self._canonical_name(name)
        if not canonical:
            return None

        rule = self._portion_rule(canonical)
        role = self._normalize_role(role) or self._infer_role(canonical)

        explicit_grams = safe_float(grams, 0.0)
        if explicit_grams <= 0:
            explicit_grams = self._default_grams(
                canonical=canonical,
                role=role,
                profile_dict=profile_dict,
                meal_type=meal_type,
            )

        state = (
            self._normalize_state(state)
            or self._normalize_state(rule.get("state"))
            or "raw"
        )

        typical, min_g, max_g = self._portion_bounds(
            canonical=canonical,
            role=role,
            explicit_grams=explicit_grams,
        )

        if optional:
            min_g = 0.0

        grams = max(min_g, min(max_g, explicit_grams))

        return {
            "name": canonical,
            "grams": round(float(grams), 1),
            "state": state,
            "role": role,
            "optional": bool(optional),
            "_typical_g": round(float(typical), 1),
            "_min_g": round(float(min_g), 1),
            "_max_g": round(float(max_g), 1),
            "_amount_source": str(amount_source or "unknown"),
        }

    def _maybe_convert_recipe_grams_to_serving(
        self,
        grams: float,
        item: Dict[str, Any],
        recipe: Dict[str, Any],
        source: Dict[str, Any],
        servings: float,
    ) -> float:
        if grams <= 0:
            return 0.0

        scope = str(
            item.get("amount_scope")
            or item.get("grams_scope")
            or item.get("scope")
            or source.get("amount_scope")
            or recipe.get("amount_scope")
            or ""
        ).lower().strip()

        if scope in {"per_serving", "serving", "single_serving", "one_serving"}:
            return grams

        if scope in {"total_recipe", "whole_recipe", "recipe_total", "batch"}:
            return grams / max(servings, 1.0)

        # Если явно есть servings > 1 и total_weight_g/serving_weight_g,
        # чаще всего ingredients_detail хранит вес всего рецепта.
        has_recipe_total_markers = any(
            key in source or key in recipe
            for key in ("total_weight_g", "serving_weight_g", "serving_model")
        )

        if servings > 1.0 and has_recipe_total_markers:
            return grams / servings

        return grams

    def _dedupe_ingredients(self, ingredients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Объединяет одинаковые canonical ингредиенты.
        Например, если в рецепте egg и eggs после alias стали egg.
        """
        by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for item in ingredients:
            name = str(item.get("name", "")).strip()
            state = str(item.get("state", "")).strip()
            if not name:
                continue

            key = (name, state)

            if key not in by_key:
                by_key[key] = dict(item)
                continue

            by_key[key]["grams"] = round(
                safe_float(by_key[key].get("grams"), 0.0)
                + safe_float(item.get("grams"), 0.0),
                1,
            )

            by_key[key]["_min_g"] = round(
                safe_float(by_key[key].get("_min_g"), 0.0)
                + safe_float(item.get("_min_g"), 0.0),
                1,
            )

            by_key[key]["_max_g"] = round(
                safe_float(by_key[key].get("_max_g"), 0.0)
                + safe_float(item.get("_max_g"), 0.0),
                1,
            )

        return list(by_key.values())

    # ──────────────────────────────────────────────
    # CANDIDATE GENERATION
    # ──────────────────────────────────────────────

    def _generate_candidate_portions(
        self,
        base_ingredients: List[Dict[str, Any]],
        base_nutrition: Dict[str, Any],
        goal: str,
        meal_type: str,
        slot_target_calories: float,
        slot_macro_targets: Dict[str, float],
    ) -> List[List[Dict[str, Any]]]:
        candidates: List[List[Dict[str, Any]]] = []
        seen = set()

        is_soup_like_base = self._is_soup_like_ingredients(base_ingredients, base_nutrition)

        def add_candidate(ingredients: List[Dict[str, Any]]) -> None:
            if len(candidates) >= self.max_candidates:
                return

            ingredients = self._cap_candidate_eaten_weight(
                ingredients=ingredients,
                meal_type=meal_type,
                slot_target_calories=slot_target_calories,
                is_soup_like=is_soup_like_base,
            )

            sig = self._ingredients_signature(ingredients)
            if sig in seen:
                return

            seen.add(sig)
            candidates.append(ingredients)

        add_candidate(self._strip_internal_fields(base_ingredients))

        base_cal = safe_float(base_nutrition.get("calories"), 0.0)
        base_p = safe_float(base_nutrition.get("protein"), 0.0)
        base_f = safe_float(base_nutrition.get("fat"), 0.0)
        base_c = safe_float(base_nutrition.get("carbs"), 0.0)

        target_p = safe_float(slot_macro_targets.get("protein_g"), 0.0)
        target_f = safe_float(slot_macro_targets.get("fat_g"), 0.0)
        target_c = safe_float(slot_macro_targets.get("carbs_g"), 0.0)

        global_ideal = self._ratio_target(slot_target_calories, base_cal, 1.0, 0.55, 1.85)
        protein_ideal = self._ratio_target(target_p, base_p, 1.0, 0.55, 1.95)
        carbs_ideal = self._ratio_target(target_c, base_c, 1.0, 0.45, 1.85)
        fat_ideal = self._ratio_target(target_f, base_f, 1.0, 0.35, 1.45)

        global_opts = self._around(global_ideal, spread=0.18, low=0.55, high=1.85)
        global_opts = self._merge_options(global_opts, [0.70, 0.85, 1.0, 1.15, 1.35])

        protein_opts = self._around(protein_ideal, spread=0.22, low=0.55, high=1.95)
        carbs_opts = self._around(carbs_ideal, spread=0.22, low=0.45, high=1.85)
        fat_opts = self._around(fat_ideal, spread=0.25, low=0.35, high=1.45)

        if goal == "weight_loss":
            veg_opts = [1.0, 1.15, 1.35, 1.55]
        elif goal == "muscle_gain":
            veg_opts = [0.85, 1.0, 1.15, 1.30]
        else:
            veg_opts = [0.90, 1.0, 1.15, 1.30]

        # 1) Глобальные масштабы.
        for global_mult in global_opts:
            add_candidate(
                self._scale_ingredients(
                    base_ingredients,
                    global_multiplier=global_mult,
                    role_multipliers={},
                )
            )

        has_protein = self._has_role(base_ingredients, {"protein", "dairy"})
        has_carbs = self._has_role(base_ingredients, {"carbs"})
        has_fat = self._has_role(base_ingredients, {"fat"})
        has_vegetable = self._has_role(base_ingredients, {"vegetable", "fruit"})

        # 2) Целевые комбинации по макросам.
        for global_mult in global_opts:
            for protein_mult in (protein_opts if has_protein else [1.0]):
                for carbs_mult in (carbs_opts if has_carbs else [1.0]):
                    for fat_mult in (fat_opts if has_fat else [1.0]):
                        for veg_mult in (veg_opts if has_vegetable else [1.0]):
                            role_multipliers = {
                                "protein": protein_mult,
                                "dairy": protein_mult,
                                "carbs": carbs_mult,
                                "fat": fat_mult,
                                "vegetable": veg_mult,
                                "fruit": veg_mult,
                            }

                            add_candidate(
                                self._scale_ingredients(
                                    base_ingredients,
                                    global_multiplier=global_mult,
                                    role_multipliers=role_multipliers,
                                )
                            )

                            if len(candidates) >= self.max_candidates:
                                return candidates

        return candidates

    def _scale_ingredients(
        self,
        ingredients: List[Dict[str, Any]],
        global_multiplier: float,
        role_multipliers: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        result = []

        for item in ingredients:
            role = self._normalize_role(item.get("role")) or "other"

            base_g = safe_float(item.get("grams"), 0.0)
            min_g = safe_float(item.get("_min_g"), 0.0)
            max_g = safe_float(item.get("_max_g"), max(base_g, 1.0) * 2.0)

            role_multiplier = role_multipliers.get(role, 1.0)

            if role in self.LOW_SCALING_ROLES:
                # Соль, специи, соусы и вода не должны улетать в 2 раза.
                scale = clamp(global_multiplier, 0.85, 1.15)
                if role in {"sauce", "condiment", "liquid", "broth", "water"}:
                    scale = clamp(global_multiplier, 0.75, 1.25)
            else:
                scale = global_multiplier * role_multiplier

            grams = base_g * scale
            grams = max(min_g, min(max_g, grams))

            if item.get("optional") and grams < 1.0:
                grams = 0.0

            clean = {
                "name": item["name"],
                "grams": round(float(grams), 1),
                "state": item.get("state", "raw"),
                "role": role,
            }

            # Нулевые optional не отправляем в NutritionEngine.
            if clean["grams"] > 0:
                result.append(clean)

        return result

    # ──────────────────────────────────────────────
    # SCORING
    # ──────────────────────────────────────────────

    def _score_portion(
        self,
        ingredients: List[Dict[str, Any]],
        nutrition: Dict[str, Any],
        base_ingredients: List[Dict[str, Any]],
        goal: str,
        meal_type: str,
        slot_target_calories: float,
        slot_macro_targets: Dict[str, float],
    ) -> Dict[str, Any]:
        calories = safe_float(nutrition.get("calories"), 0.0)
        protein = safe_float(nutrition.get("protein"), 0.0)
        fat = safe_float(nutrition.get("fat"), 0.0)
        carbs = safe_float(nutrition.get("carbs"), 0.0)

        target_p = safe_float(slot_macro_targets.get("protein_g"), 0.0)
        target_f = safe_float(slot_macro_targets.get("fat_g"), 0.0)
        target_c = safe_float(slot_macro_targets.get("carbs_g"), 0.0)

        calorie_fit = self._fit_score(calories, slot_target_calories, sigma=0.20)

        protein_fit = self._macro_fit(
            actual=protein,
            target=target_p,
            sigma_under=0.30,
            sigma_over=0.55,
        )
        fat_fit = self._macro_fit(
            actual=fat,
            target=target_f,
            sigma_under=0.45,
            sigma_over=0.30,
        )
        carbs_fit = self._macro_fit(
            actual=carbs,
            target=target_c,
            sigma_under=0.42,
            sigma_over=0.38,
        )

        macro_fit = clamp((protein_fit * 1.15 + fat_fit * 0.90 + carbs_fit) / 3.05)

        protein_floor = 1.0
        if target_p > 0:
            protein_floor = clamp(protein / max(target_p * 0.82, 1.0))

        category_balance = clamp(safe_float(nutrition.get("category_balance"), 0.55))
        satiety = clamp(safe_float(nutrition.get("satiety_score"), 0.0) / 10.0)
        meal_weight_score = self._meal_weight_score(nutrition, meal_type, slot_target_calories)
        portion_feasibility = self._portion_feasibility_score(ingredients, base_ingredients)
        goal_score = self._goal_score(nutrition, goal)

        is_soup_like = self._is_soup_like_ingredients(ingredients, nutrition)
        meal_weight_penalty = self._meal_weight_penalty(
            nutrition=nutrition,
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            is_soup_like=is_soup_like,
        )

        over_calorie_penalty = self._over_target_penalty(
            actual=calories,
            target=slot_target_calories,
            tolerance=1.08,
            strength=0.35,
        )

        fat_over_penalty = self._over_target_penalty(
            actual=fat,
            target=target_f,
            tolerance=1.15,
            strength=0.25,
        )

        # Для weight_loss дополнительно штрафуем высокую плотность энергии.
        energy_density = safe_float(nutrition.get("energy_density_kcal_per_g"), 0.0)
        energy_density_penalty = 0.0
        if goal == "weight_loss" and energy_density > 2.15:
            energy_density_penalty = clamp((energy_density - 2.15) / 2.5) * 0.14

        score = (
            0.20 * calorie_fit
            + 0.25 * macro_fit
            + 0.10 * protein_floor
            + 0.10 * meal_weight_score
            + 0.10 * portion_feasibility
            + 0.08 * category_balance
            + 0.07 * satiety
            + 0.10 * goal_score
            - over_calorie_penalty
            - fat_over_penalty
            - energy_density_penalty
            - meal_weight_penalty
        )

        score = clamp(score)

        return {
            "score": score,
            "components": {
                "calorie_fit": round(calorie_fit, 3),
                "macro_fit": round(macro_fit, 3),
                "protein_fit": round(protein_fit, 3),
                "fat_fit": round(fat_fit, 3),
                "carbs_fit": round(carbs_fit, 3),
                "protein_floor": round(protein_floor, 3),
                "meal_weight_score": round(meal_weight_score, 3),
                "portion_feasibility": round(portion_feasibility, 3),
                "category_balance": round(category_balance, 3),
                "satiety": round(satiety, 3),
                "goal_score": round(goal_score, 3),
                "over_calorie_penalty": round(over_calorie_penalty, 3),
                "fat_over_penalty": round(fat_over_penalty, 3),
                "energy_density_penalty": round(energy_density_penalty, 3),
                "meal_weight_penalty": round(meal_weight_penalty, 3),
                "is_soup_like": is_soup_like,
            },
        }

    def _fit_score(self, actual: float, target: float, sigma: float = 0.25) -> float:
        if actual <= 0 or target <= 0:
            return 0.0
        ratio = actual / target
        return clamp(math.exp(-((ratio - 1.0) ** 2) / (2 * sigma ** 2)))

    def _macro_fit(
        self,
        actual: float,
        target: float,
        sigma_under: float,
        sigma_over: float,
    ) -> float:
        if target <= 0:
            return 1.0
        if actual <= 0:
            return 0.0

        ratio = actual / target
        sigma = sigma_under if ratio < 1.0 else sigma_over

        return clamp(math.exp(-((ratio - 1.0) ** 2) / (2 * sigma ** 2)))

    def _over_target_penalty(
        self,
        actual: float,
        target: float,
        tolerance: float,
        strength: float,
    ) -> float:
        if target <= 0 or actual <= target * tolerance:
            return 0.0

        excess_ratio = (actual / target) - tolerance
        return clamp(excess_ratio / 0.75) * strength

    def _meal_weight_score(
        self,
        nutrition: Dict[str, Any],
        meal_type: str,
        slot_target_calories: float,
    ) -> float:
        eaten_weight = safe_float(nutrition.get("eaten_weight_g"), 0.0)
        if eaten_weight <= 0:
            return 0.45

        if meal_type == "breakfast":
            min_w, ideal_w, max_w = 220.0, 380.0, 620.0
        elif meal_type in {"snack", "snack2"}:
            min_w, ideal_w, max_w = 80.0, 180.0, 320.0
        else:
            min_w, ideal_w, max_w = 300.0, 520.0, 850.0

        # Масштабируем ожидание по калориям слота.
        calorie_scale = clamp(slot_target_calories / 650.0, 0.65, 1.35)
        min_w *= calorie_scale
        ideal_w *= calorie_scale
        max_w *= calorie_scale

        if min_w <= eaten_weight <= max_w:
            distance = abs(eaten_weight - ideal_w) / max(ideal_w, 1.0)
            return clamp(1.0 - distance * 0.45)

        if eaten_weight < min_w:
            return clamp(eaten_weight / max(min_w, 1.0))

        return clamp(max_w / max(eaten_weight, 1.0))

    def _meal_weight_penalty(
        self,
        nutrition: Dict[str, Any],
        meal_type: str,
        slot_target_calories: float,
        is_soup_like: bool = False,
    ) -> float:
        eaten_weight = safe_float(nutrition.get("eaten_weight_g"), 0.0)
        if eaten_weight <= 0:
            return 0.0

        hard_limit = self._hard_eaten_weight_limit(
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            is_soup_like=is_soup_like,
        )

        if eaten_weight <= hard_limit:
            return 0.0

        ratio = eaten_weight / max(hard_limit, 1.0)

        # После hard_limit штраф должен быть сильным: иначе суп может выиграть
        # за счёт calorie_fit/macro_fit и попасть в план весом > 1 кг.
        penalty = 0.22 + clamp((ratio - 1.0) / 0.65) * 0.58
        return clamp(penalty, 0.0, 0.80)


    def _hard_eaten_weight_limit(
        self,
        meal_type: str,
        slot_target_calories: float,
        is_soup_like: bool = False,
    ) -> float:
        meal_type = str(meal_type or "lunch").lower().strip()

        limits = (
            self.SOUP_EATEN_WEIGHT_LIMITS
            if is_soup_like
            else self.HARD_EATEN_WEIGHT_LIMITS
        )

        base_limit = float(limits.get(meal_type, limits.get("lunch", 900.0)))

        # Для 800–900 kcal слота можно чуть больше веса, но не бесконечно.
        calorie_factor = clamp(slot_target_calories / 650.0, 0.85, 1.12)
        return round(base_limit * calorie_factor, 1)


    def _is_soup_like_ingredients(
        self,
        ingredients: List[Dict[str, Any]],
        nutrition: Optional[Dict[str, Any]] = None,
    ) -> bool:
        total = 0.0
        liquid = 0.0
        vegetable = 0.0

        for item in ingredients or []:
            grams = safe_float(item.get("grams"), 0.0)
            role = self._normalize_role(item.get("role")) or "other"
            name = self._normalize_key(item.get("name"))

            total += grams

            if role in {"liquid", "broth", "water"} or any(
                token in name for token in ("broth", "stock", "water")
            ):
                liquid += grams

            if role in {"vegetable", "fruit"}:
                vegetable += grams

        if total <= 0:
            return False

        liquid_share = liquid / total
        vegetable_share = vegetable / total

        if liquid >= 180.0 and liquid_share >= 0.28:
            return True

        # Овощной суп/рагу с большим объёмом и низкой плотностью энергии.
        if nutrition:
            energy_density = safe_float(nutrition.get("energy_density_kcal_per_g"), 0.0)
            eaten_weight = safe_float(nutrition.get("eaten_weight_g"), total)
            if eaten_weight >= 650.0 and energy_density > 0 and energy_density < 1.05:
                if liquid_share >= 0.18 or vegetable_share >= 0.45:
                    return True

        return False


    def _cap_candidate_eaten_weight(
        self,
        ingredients: List[Dict[str, Any]],
        meal_type: str,
        slot_target_calories: float,
        is_soup_like: bool = False,
    ) -> List[Dict[str, Any]]:
        if not ingredients:
            return ingredients

        hard_limit = self._hard_eaten_weight_limit(
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            is_soup_like=is_soup_like,
        )

        total = sum(safe_float(x.get("grams"), 0.0) for x in ingredients)
        if total <= hard_limit or total <= 0:
            return ingredients

        protected_roles = {"seasoning", "spice", "herb", "salt"}
        protected_weight = sum(
            safe_float(x.get("grams"), 0.0)
            for x in ingredients
            if (self._normalize_role(x.get("role")) or "other") in protected_roles
        )

        scalable_weight = max(total - protected_weight, 0.0)
        allowed_scalable = max(hard_limit - protected_weight, 1.0)
        scale = clamp(allowed_scalable / max(scalable_weight, 1.0), 0.35, 1.0)

        capped = []
        for item in ingredients:
            role = self._normalize_role(item.get("role")) or "other"
            clean = dict(item)

            if role not in protected_roles:
                grams = safe_float(clean.get("grams"), 0.0) * scale
                min_g = safe_float(clean.get("_min_g"), 0.0)

                # Для liquid/vegetable в супе min_g не должен мешать sanity-cap.
                if is_soup_like and role in {"liquid", "vegetable"}:
                    min_g = min(min_g, grams)

                clean["grams"] = round(max(min_g, grams), 1)

            capped.append(clean)

        return capped


    def _portion_feasibility_score(
        self,
        ingredients: List[Dict[str, Any]],
        base_ingredients: List[Dict[str, Any]],
    ) -> float:
        base_by_name = {
            (x.get("name"), x.get("state")): x
            for x in base_ingredients
            if x.get("name")
        }

        scores = []

        for item in ingredients:
            role = self._normalize_role(item.get("role")) or "other"

            if role in self.LOW_SCALING_ROLES:
                continue

            key = (item.get("name"), item.get("state"))
            base = base_by_name.get(key)

            grams = safe_float(item.get("grams"), 0.0)

            if base:
                typical = safe_float(base.get("_typical_g"), safe_float(base.get("grams"), grams))
                min_g = safe_float(base.get("_min_g"), 0.0)
                max_g = safe_float(base.get("_max_g"), max(grams, 1.0) * 2)
            else:
                typical = grams
                min_g = 0.0
                max_g = max(grams, 1.0) * 2

            if grams < min_g * 0.95 or grams > max_g * 1.05:
                scores.append(0.0)
                continue

            ratio = grams / max(typical, 1.0)
            # 1.0 = идеально, 0.5/2.0 ещё допустимо, дальше хуже.
            score = math.exp(-((math.log(max(ratio, 0.01))) ** 2) / (2 * 0.55 ** 2))
            scores.append(clamp(score))

        if not scores:
            return 0.85

        return clamp(sum(scores) / len(scores))

    def _goal_score(self, nutrition: Dict[str, Any], goal: str) -> float:
        calories = max(1.0, safe_float(nutrition.get("calories"), 0.0))
        protein = safe_float(nutrition.get("protein"), 0.0)
        fat = safe_float(nutrition.get("fat"), 0.0)
        carbs = safe_float(nutrition.get("carbs"), 0.0)
        fiber = safe_float(nutrition.get("fiber"), 0.0)

        protein_density = (protein * 4.0) / calories
        fat_density = (fat * 9.0) / calories
        carb_density = (carbs * 4.0) / calories
        fiber_per_100kcal = fiber / max(calories / 100.0, 1.0)

        if goal == "weight_loss":
            return clamp(
                0.42 * protein_density
                + 0.24 * clamp(fiber_per_100kcal / 3.0)
                + 0.22 * (1.0 - fat_density)
                + 0.12 * (1.0 - carb_density)
            )

        if goal == "muscle_gain":
            return clamp(
                0.42 * protein_density
                + 0.28 * carb_density
                + 0.15 * clamp(calories / 850.0)
                + 0.15 * (1.0 - fat_density)
            )

        return clamp(
            0.35 * protein_density
            + 0.25 * carb_density
            + 0.20 * (1.0 - fat_density)
            + 0.20
        )

    # ──────────────────────────────────────────────
    # NUTRITION ENGINE CALLS
    # ──────────────────────────────────────────────

    def _calculate_nutrition(
        self,
        ingredients: List[Dict[str, Any]],
        profile_dict: Optional[Dict[str, Any]],
        meal_type: str,
    ) -> Dict[str, Any]:
        clean = self._strip_internal_fields(ingredients)

        try:
            result = self.nutrition_engine.calculate(
                clean,
                profile=profile_dict,
                meal_type=meal_type,
                include_items=False,
            )
        except TypeError:
            try:
                result = self.nutrition_engine.calculate(
                    clean,
                    profile=profile_dict,
                    meal_type=meal_type,
                )
            except TypeError:
                result = self.nutrition_engine.calculate(clean)
        except Exception as exc:
            logger.warning(f"Nutrition calculation failed: {exc}")
            result = {}

        if not isinstance(result, dict):
            result = {}

        for key in [
            "calories", "protein", "fat", "carbs", "fiber", "sugar",
            "sodium_mg", "saturated_fat", "eaten_weight_g", "nutrition_weight_g",
            "volume_ml", "energy_density_kcal_per_g", "satiety_score",
            "category_balance",
        ]:
            result.setdefault(key, 0.0)

        return result

    def _strip_internal_fields(self, ingredients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []

        for item in ingredients or []:
            if not isinstance(item, dict):
                continue

            clean = {
                "name": item.get("name"),
                "grams": round(safe_float(item.get("grams"), 0.0), 1),
            }

            if item.get("state"):
                clean["state"] = item.get("state")

            if item.get("role"):
                clean["role"] = item.get("role")

            result.append(clean)

        return result

    # ──────────────────────────────────────────────
    # PORTION RULES / GROUPS
    # ──────────────────────────────────────────────

    def _portion_rule(self, canonical: str) -> Dict[str, Any]:
        rule = self.portion_rules.get(canonical, {})
        return rule if isinstance(rule, dict) else {}

    def _portion_bounds(
        self,
        canonical: str,
        role: str,
        explicit_grams: float,
    ) -> Tuple[float, float, float]:
        rule = self._portion_rule(canonical)

        typical = safe_float(
            rule.get("typical_g", rule.get("typical", rule.get("default_g"))),
            0.0,
        )
        min_g = safe_float(rule.get("min_g", rule.get("min")), 0.0)
        max_g = safe_float(rule.get("max_g", rule.get("max")), 0.0)

        if typical <= 0:
            _, default_typical, _ = self.DEFAULT_PORTION_RANGES.get(
                role,
                self.DEFAULT_PORTION_RANGES["other"],
            )
            typical = explicit_grams if explicit_grams > 0 else default_typical

        if min_g <= 0 or max_g <= 0:
            default_min, _, default_max = self.DEFAULT_PORTION_RANGES.get(
                role,
                self.DEFAULT_PORTION_RANGES["other"],
            )
            min_g = min_g if min_g > 0 else default_min
            max_g = max_g if max_g > 0 else default_max

        # Для специй/соли не раздуваем лимиты.
        if role in {"seasoning", "spice", "herb", "salt"} and explicit_grams > 0:
            typical = explicit_grams
            min_g = min(min_g, explicit_grams * 0.5)
            max_g = min(max_g, max(explicit_grams * 1.8, explicit_grams + 2.0))

        if explicit_grams > max_g:
            max_g = max(explicit_grams * 1.25, max_g)

        if explicit_grams > 0 and explicit_grams < min_g:
            min_g = max(0.0, explicit_grams * 0.65)

        if max_g < min_g:
            max_g = min_g

        return typical, min_g, max_g

    def _default_grams(
        self,
        canonical: str,
        role: str,
        profile_dict: Optional[Dict[str, Any]],
        meal_type: str,
    ) -> float:
        # Если NutritionEngine уже умеет resolve portion — используем его.
        get_portion_g = getattr(self.nutrition_engine, "get_portion_g", None)

        if callable(get_portion_g):
            try:
                grams = get_portion_g(
                    canonical,
                    profile=profile_dict,
                    meal_type=meal_type,
                )
                if grams and grams > 0:
                    return float(grams)
            except Exception:
                pass

        rule = self._portion_rule(canonical)
        grams = safe_float(
            rule.get("typical_g", rule.get("typical", rule.get("default_g"))),
            0.0,
        )
        if grams > 0:
            return grams

        _, default_typical, _ = self.DEFAULT_PORTION_RANGES.get(
            role,
            self.DEFAULT_PORTION_RANGES["other"],
        )
        return default_typical

    def _build_group_lookup(self, groups: Dict[str, Any]) -> Dict[str, str]:
        lookup: Dict[str, str] = {}

        if not isinstance(groups, dict):
            return lookup

        for key, value in groups.items():
            key_norm = self._normalize_key(key)

            if isinstance(value, list):
                role = self._normalize_role(key_norm)
                for item in value:
                    item_norm = self._normalize_key(item)
                    if item_norm:
                        lookup[item_norm] = role
                lookup[key_norm] = role

            elif isinstance(value, str):
                lookup[key_norm] = self._normalize_role(value)

            elif isinstance(value, dict):
                role = (
                    value.get("role")
                    or value.get("category")
                    or value.get("group")
                    or value.get("type")
                    or key_norm
                )
                lookup[key_norm] = self._normalize_role(role)

                aliases = value.get("aliases", [])
                if isinstance(aliases, list):
                    for alias in aliases:
                        alias_norm = self._normalize_key(alias)
                        if alias_norm:
                            lookup[alias_norm] = lookup[key_norm]

        return lookup

    def _infer_role(self, canonical: str) -> str:
        key = self._normalize_key(canonical)

        if key in self.group_lookup:
            return self.group_lookup[key]

        # Alias fallback.
        alias_target = self.food_aliases.get(key)
        if alias_target:
            alias_key = self._normalize_key(alias_target)
            if alias_key in self.group_lookup:
                return self.group_lookup[alias_key]

        protein_words = [
            "chicken", "beef", "turkey", "pork", "fish", "salmon", "tuna",
            "shrimp", "egg", "tofu", "lamb", "cod", "crab", "yogurt",
            "cottage_cheese", "cheese", "beans", "lentils", "chickpeas",
        ]
        carb_words = [
            "rice", "potato", "pasta", "spaghetti", "noodles", "bread",
            "tortilla", "oats", "oatmeal", "buckwheat", "bulgur", "quinoa",
            "flour", "cornmeal", "couscous",
        ]
        fat_words = [
            "oil", "butter", "ghee", "cream", "mayo", "mayonnaise",
            "nuts", "almond", "peanut", "avocado", "bacon",
        ]
        vegetable_words = [
            "broccoli", "carrot", "cabbage", "tomato", "cucumber",
            "lettuce", "spinach", "pepper", "zucchini", "onion",
            "garlic", "asparagus", "cauliflower", "eggplant", "peas",
        ]
        fruit_words = [
            "apple", "banana", "berries", "strawberry", "blueberry",
            "orange", "lemon", "lime", "grape",
        ]
        seasoning_words = [
            "salt", "pepper", "paprika", "cumin", "thyme", "dill",
            "parsley", "cilantro", "cinnamon", "bay_leaf", "oregano",
            "basil", "spice", "seasoning",
        ]
        sauce_words = [
            "sauce", "ketchup", "mustard", "soy_sauce", "vinegar",
            "dressing", "tahini", "salsa",
        ]
        liquid_words = [
            "water", "broth", "stock", "milk", "wine", "juice",
        ]

        if any(w in key for w in seasoning_words):
            return "seasoning"
        if any(w in key for w in sauce_words):
            return "sauce"
        if any(w in key for w in liquid_words):
            return "liquid"
        if any(w in key for w in protein_words):
            return "protein"
        if any(w in key for w in carb_words):
            return "carbs"
        if any(w in key for w in fat_words):
            return "fat"
        if any(w in key for w in vegetable_words):
            return "vegetable"
        if any(w in key for w in fruit_words):
            return "fruit"

        return "other"

    def _normalize_role(self, value: Any) -> str:
        role = self._normalize_key(value)
        if not role:
            return ""

        aliases = {
            "protein_food": "protein",
            "meat": "protein",
            "fish": "protein",
            "seafood": "protein",
            "legume": "protein",
            "legumes": "protein",

            "carb": "carbs",
            "carbohydrate": "carbs",
            "carbohydrates": "carbs",
            "grain": "carbs",
            "grains": "carbs",
            "starch": "carbs",
            "starchy": "carbs",

            "vegetables": "vegetable",
            "veg": "vegetable",

            "fruits": "fruit",

            "fats": "fat",
            "oil": "fat",
            "oils": "fat",

            "spices": "seasoning",
            "herbs": "seasoning",
            "condiments": "sauce",
            "fluid": "liquid",
            "liquids": "liquid",
        }

        return aliases.get(role, role)

    # ──────────────────────────────────────────────
    # CACHE
    # ──────────────────────────────────────────────

    def _cache_set(self, key: str, value: Dict[str, Any]) -> None:
        if not self.enable_cache:
            return

        if len(self._optimization_cache) >= self.cache_max_size:
            keys = list(self._optimization_cache.keys())
            for old_key in keys[: max(1, len(keys) // 2)]:
                self._optimization_cache.pop(old_key, None)

        cached = copy.deepcopy(value)
        cached.setdefault("portion", {})
        cached["portion"]["cache_hit"] = False
        self._optimization_cache[key] = cached

    def _portion_cache_key(
        self,
        recipe: Dict[str, Any],
        profile_dict: Optional[Dict[str, Any]],
        meal_type: str,
        slot_target_calories: float,
        slot_macro_targets: Dict[str, float],
    ) -> str:
        payload = {
            "recipe": self._recipe_cache_view(recipe),
            "profile": self._profile_cache_view(profile_dict),
            "meal_type": meal_type,
            "slot_target_calories": round(float(slot_target_calories), 1),
            "slot_macro_targets": {
                key: round(float(slot_macro_targets.get(key, 0.0)), 1)
                for key in self.MACRO_KEYS
            },
            "optimizer_version": "prod_v2_fast_cached",
        }

        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _recipe_cache_view(self, recipe: Dict[str, Any]) -> Dict[str, Any]:
        source = recipe.get("source", {})
        if not isinstance(source, dict):
            source = {}

        detail = source.get("ingredients_detail") or recipe.get("ingredients_detail")
        if isinstance(detail, list):
            ingredients_view = []
            for item in detail:
                if isinstance(item, dict):
                    ingredients_view.append({
                        "name": self._normalize_key(
                            item.get("canonical_name")
                            or item.get("name")
                            or item.get("ingredient")
                        ),
                        "grams": round(safe_float(
                            item.get("grams", item.get("weight_g", item.get("amount_g"))),
                            0.0,
                        ), 1),
                        "state": self._normalize_state(item.get("state")),
                        "role": self._normalize_role(item.get("role") or item.get("category")),
                    })
        else:
            ingredients_view = []
            for item in recipe.get("ingredients", []) or []:
                if isinstance(item, str):
                    ingredients_view.append({"name": self._normalize_key(item)})
                elif isinstance(item, dict):
                    ingredients_view.append({
                        "name": self._normalize_key(
                            item.get("canonical_name")
                            or item.get("name")
                            or item.get("ingredient")
                        ),
                        "grams": round(safe_float(
                            item.get("grams", item.get("weight_g", item.get("amount"))),
                            0.0,
                        ), 1),
                        "state": self._normalize_state(item.get("state")),
                    })

        return {
            "name": str(recipe.get("name") or source.get("name") or "").lower().strip(),
            "servings": self._recipe_servings(recipe, source),
            "ingredients": ingredients_view,
        }

    def _profile_cache_view(self, profile_dict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        profile_dict = profile_dict or {}

        keys = [
            "goal", "sex", "age", "height_cm", "weight_kg", "activity_level",
            "target_calories", "protein_target_g", "fat_target_g", "carb_limit_g",
        ]

        return {key: profile_dict.get(key) for key in keys}

    # ──────────────────────────────────────────────
    # GENERIC HELPERS
    # ──────────────────────────────────────────────

    def _load_json(self, path: Path, default: Any) -> Any:
        try:
            if not path.exists():
                logger.warning(f"JSON config not found: {path}")
                return default

            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as exc:
            logger.warning(f"Failed to load JSON config {path}: {exc}")
            return default

    def _profile_as_dict(self, user_profile: Any) -> Optional[Dict[str, Any]]:
        if user_profile is None:
            return None
        if isinstance(user_profile, dict):
            return dict(user_profile)
        data = getattr(user_profile, "__dict__", None)
        if isinstance(data, dict):
            return dict(data)
        return None

    def _profile_get(self, profile_dict: Optional[Dict[str, Any]], key: str, default: Any = None) -> Any:
        if not profile_dict:
            return default
        return profile_dict.get(key, default)

    def _normalize_goal(self, goal: Any) -> str:
        key = str(goal or "balanced").strip().lower()
        return self.GOAL_ALIASES.get(key, "balanced")

    def _normalize_key(self, value: Any) -> str:
        return (
            str(value or "")
            .lower()
            .strip()
            .replace("-", "_")
            .replace(" ", "_")
        )

    def _canonical_name(self, name: Any) -> str:
        raw = self._normalize_key(name)
        if not raw:
            return ""

        normalizer = getattr(self.nutrition_engine, "name_normalizer", None)
        if normalizer is not None:
            try:
                canonical = normalizer.canonical(raw)
                if canonical:
                    return self._normalize_key(canonical)
            except Exception:
                pass

        if raw in self.food_aliases:
            return self._normalize_key(self.food_aliases[raw])

        return raw

    def _normalize_state(self, state: Any) -> str:
        value = str(state or "").lower().strip()
        if value in {"raw", "uncooked"}:
            return "raw"
        if value in {"cooked", "prepared", "boiled", "fried", "baked", "roasted"}:
            return "cooked"
        return value

    def _recipe_servings(self, recipe: Dict[str, Any], source: Dict[str, Any]) -> float:
        serving_model = source.get("serving_model") or recipe.get("serving_model")

        if isinstance(serving_model, dict):
            servings = safe_float(
                serving_model.get("servings")
                or serving_model.get("portion_count")
                or serving_model.get("persons"),
                0.0,
            )
            if servings > 0:
                return max(1.0, servings)

        servings = safe_float(
            source.get("servings")
            or recipe.get("servings")
            or source.get("persons")
            or recipe.get("persons"),
            1.0,
        )

        return max(1.0, servings)

    def _normalize_macro_targets(self, slot_macro_targets: Dict[str, Any]) -> Dict[str, float]:
        slot_macro_targets = slot_macro_targets or {}
        return {
            "protein_g": max(0.0, safe_float(slot_macro_targets.get("protein_g"), 0.0)),
            "fat_g": max(0.0, safe_float(slot_macro_targets.get("fat_g"), 0.0)),
            "carbs_g": max(0.0, safe_float(slot_macro_targets.get("carbs_g"), 0.0)),
        }

    def _fallback_slot_calories(
        self,
        profile_dict: Optional[Dict[str, Any]],
        meal_type: str,
    ) -> float:
        target_calories = safe_float(self._profile_get(profile_dict, "target_calories", 2000), 2000)

        weights = {
            "breakfast": 0.30,
            "lunch": 0.40,
            "dinner": 0.30,
            "snack": 0.15,
            "snack2": 0.15,
        }

        return target_calories * weights.get(meal_type, 0.35)

    def _fallback_slot_macros(
        self,
        profile_dict: Optional[Dict[str, Any]],
        slot_target_calories: float,
    ) -> Dict[str, float]:
        protein = safe_float(self._profile_get(profile_dict, "protein_target_g"), 0.0)
        fat = safe_float(self._profile_get(profile_dict, "fat_target_g"), 0.0)

        # fallback: 28/27/45 по калориям
        if protein <= 0:
            protein = (slot_target_calories * 0.28) / 4.0
        else:
            protein = protein * (slot_target_calories / max(safe_float(
                self._profile_get(profile_dict, "target_calories", 2000),
                2000,
            ), 1.0))

        if fat <= 0:
            fat = (slot_target_calories * 0.27) / 9.0
        else:
            fat = fat * (slot_target_calories / max(safe_float(
                self._profile_get(profile_dict, "target_calories", 2000),
                2000,
            ), 1.0))

        remaining = slot_target_calories - protein * 4.0 - fat * 9.0
        carbs = max(0.0, remaining / 4.0)

        return {
            "protein_g": round(protein, 1),
            "fat_g": round(fat, 1),
            "carbs_g": round(carbs, 1),
        }

    def _ratio_target(
        self,
        target: float,
        actual: float,
        default: float,
        low: float,
        high: float,
    ) -> float:
        if target <= 0 or actual <= 0:
            return default
        return clamp(target / actual, low, high)

    def _around(self, value: float, spread: float, low: float, high: float) -> List[float]:
        options = [
            value * (1.0 - spread),
            value,
            value * (1.0 + spread),
            1.0,
        ]
        return self._merge_options([], options, low=low, high=high)

    def _merge_options(
        self,
        base: List[float],
        extra: List[float],
        low: float = 0.35,
        high: float = 1.95,
    ) -> List[float]:
        values = []
        seen = set()

        for value in list(base) + list(extra):
            value = round(clamp(float(value), low, high), 2)
            if value in seen:
                continue
            seen.add(value)
            values.append(value)

        values.sort()
        return values

    def _has_role(self, ingredients: List[Dict[str, Any]], roles: Iterable[str]) -> bool:
        roles = set(roles)
        return any(self._normalize_role(item.get("role")) in roles for item in ingredients)

    def _ingredients_signature(self, ingredients: List[Dict[str, Any]]) -> str:
        parts = []
        for item in ingredients:
            parts.append(
                f"{item.get('name')}:{item.get('state')}:{round(safe_float(item.get('grams'), 0.0), 1)}"
            )
        return "|".join(sorted(parts))

    def _empty_result(
        self,
        reason: str,
        slot_target_calories: float,
        slot_macro_targets: Dict[str, float],
    ) -> Dict[str, Any]:
        return {
            "ingredients": [],
            "nutrition": {
                "calories": 0.0,
                "protein": 0.0,
                "fat": 0.0,
                "carbs": 0.0,
                "fiber": 0.0,
                "sugar": 0.0,
                "sodium_mg": 0.0,
                "saturated_fat": 0.0,
                "eaten_weight_g": 0.0,
                "nutrition_weight_g": 0.0,
                "volume_ml": 0.0,
                "energy_density_kcal_per_g": 0.0,
                "satiety_score": 0.0,
                "category_balance": 0.0,
            },
            "portion": {
                "score": 0.0,
                "reason": reason,
                "target_calories": round(slot_target_calories, 1),
                "target_macros": slot_macro_targets,
                "tested_candidates": 0,
                "components": {},
                "cache_hit": False,
            },
        }
