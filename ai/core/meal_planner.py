from __future__ import annotations

import os
import json
import logging
from copy import deepcopy
from math import exp
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from ai.core.decision.portion_optimizer import PortionOptimizer
from ai.core.decision.recipe_candidate_reranker import RecipeCandidateReranker

logger = logging.getLogger("MealPlanner")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "ai" / "data"
MEAL_PLANNER_RULES_PATH = DATA_DIR / "meal_planner_rules.json"

def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


Ingredient = Union[str, Dict[str, Any]]


class MealPlanner:
    """
    Планировщик питания.

    Важная логика:
    - recipe["ingredients"] может быть list[str] или list[dict].
    - dict-ингредиенты НЕ теряют grams/state:
      {"name": "rice", "grams": 180, "state": "cooked"}.
    - NutritionEngine получает полные ингредиенты с граммовками.
    - Safety/Preference/Diversity получают только имена ингредиентов.
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

    ABSOLUTE_NUTRITION_KEYS = {
        "calories",
        "protein",
        "fat",
        "carbs",
        "fiber",
        "sugar",
        "sodium_mg",
        "saturated_fat",
        "eaten_weight_g",
        "nutrition_weight_g",
        "volume_ml",
    }

    DAY_TOTAL_KEYS = [
        "calories",
        "protein",
        "fat",
        "carbs",
        "fiber",
        "sugar",
        "sodium_mg",
        "saturated_fat",
        "eaten_weight_g",
        "nutrition_weight_g",
    ]

    def __init__(
        self,
        recipe_search,
        nutrition_engine,
        llm=None,
        safety_checker=None,
        preference_scorer=None,
        diversity_engine=None,
        substitution_engine=None,
        ranking_engine=None,
        portion_optimizer=None,
        recipe_reranker=None,
    ):
        self.recipe_search = recipe_search
        self.nutrition_engine = nutrition_engine
        self.llm = llm
        self.safety_checker = safety_checker
        self.preference_scorer = preference_scorer
        self.diversity_engine = diversity_engine
        self.substitution_engine = substitution_engine
        self.ranking_engine = ranking_engine
        self.max_optimized_candidates_per_slot = int(
            os.getenv("AI_FOOD_MAX_OPTIMIZED_PER_SLOT", "12")
        )
        self.portion_optimizer = portion_optimizer or PortionOptimizer(nutrition_engine)
        self.recipe_reranker = recipe_reranker or RecipeCandidateReranker(nutrition_engine)
        self.meal_planner_rules = self._load_meal_planner_rules()
        self.main_carb_lookup = self._build_group_lookup(
            self.meal_planner_rules.get("main_carb_groups", {})
        )

    def _load_json_file(self, path: Path, default: Optional[dict] = None) -> dict:
        if default is None:
            default = {}

        try:
            if not path.exists():
                logger.warning(f"JSON config not found: {path}")
                return default

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                logger.warning(f"JSON config must be object: {path}")
                return default

            return data

        except Exception as e:
            logger.warning(f"Failed to load JSON config {path}: {e}")
            return default


    def _load_meal_planner_rules(self) -> dict:
        return self._load_json_file(
            MEAL_PLANNER_RULES_PATH,
            default={
                "schema_version": "fallback",
                "main_carb_groups": {},
                "main_carb_repeat_policy": {
                    "enabled": True,
                    "same_carb_first_repeat_penalty": 0.16,
                    "same_carb_additional_repeat_penalty": 0.08,
                    "max_penalty": 0.35,
                    "allow_same_carb_per_day": 1,
                    "hard_block_after_repeats": 3
                }
            }
        )

    def _build_group_lookup(self, groups: Any) -> Dict[str, str]:
        """
        Строит lookup alias -> canonical group.

        Поддерживает prod-формат:
        {
          "rice": ["rice", "cooked_rice", ...],
          "bread": ["bread", "tortilla_flour", ...]
        }

        И безопасный fallback-формат:
        ["rice", "bread", "potato"]
        """
        lookup: Dict[str, str] = {}

        if isinstance(groups, list):
            for item in groups:
                key = self._normalize_food_key(item)
                if key:
                    lookup[key] = key
            return lookup

        if not isinstance(groups, dict):
            return lookup

        for group_name, aliases in groups.items():
            group_key = self._normalize_food_key(group_name)
            if not group_key:
                continue

            lookup[group_key] = group_key

            if isinstance(aliases, dict):
                alias_values = list(aliases.values())
            elif isinstance(aliases, list):
                alias_values = aliases
            else:
                alias_values = []

            for alias in alias_values:
                alias_key = self._normalize_food_key(alias)
                if alias_key:
                    lookup[alias_key] = group_key

        return lookup

    def _normalize_food_key(self, value: Any) -> str:
        return str(value or "").lower().strip().replace(" ", "_").replace("-", "_")

    def _rules_get(self, *path: str, default: Any = None) -> Any:
        """
        Безопасное чтение вложенных правил из ai/data/meal_planner_rules.json.
        Возвращает default, если путь отсутствует или структура не dict.
        """
        current: Any = getattr(self, "meal_planner_rules", {}) or {}

        for key in path:
            if not isinstance(current, dict):
                return default
            current = current.get(key)

        return current if current is not None else default

    def _rules_list(self, *path: str) -> List[Any]:
        value = self._rules_get(*path, default=[])
        return value if isinstance(value, list) else []

    def _normalize_rule_token(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = text.replace("-", "_").replace(" ", "_")
        while "__" in text:
            text = text.replace("__", "_")
        return text

    def _normalize_rule_text(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = text.replace("_", " ").replace("-", " ")
        while "  " in text:
            text = text.replace("  ", " ")
        return text

    def _meal_type_group_set(self, group_name: str) -> set:
        values = self._rules_list(
            "recipe_quality_rules",
            "meal_type_groups",
            group_name,
        )
        return {self._normalize_rule_token(x) for x in values if str(x).strip()}

    def _selection_quality_policy(self) -> Dict[str, Any]:
        policy = self._rules_get(
            "meal_structure_rules",
            "selection_quality_policy",
            default={},
        )
        return policy if isinstance(policy, dict) else {}

    def _day_macro_pressure_policy(self) -> Dict[str, Any]:
        policy = self._rules_get(
            "meal_structure_rules",
            "day_macro_pressure_policy",
            default={},
        )
        return policy if isinstance(policy, dict) else {}

    def _recipe_cooldown_policy(self) -> Dict[str, Any]:
        policy = self._rules_get(
            "meal_structure_rules",
            "recipe_cooldown_policy",
            default={},
        )
        return policy if isinstance(policy, dict) else {}

    def _main_carb_hard_block_penalty(self) -> float:
        """
        Штраф за hard-block повтора main_carb.

        Поддерживает две схемы JSON:
        - main_carb_repeat_policy.hard_block_penalty / max_penalty
        - recipe_quality_rules.main_carb_repeat.hard_block_penalty
        """
        root_policy = self.meal_planner_rules.get("main_carb_repeat_policy", {}) or {}
        nested_policy = self._rules_get(
            "recipe_quality_rules",
            "main_carb_repeat",
            default={},
        )
        if not isinstance(nested_policy, dict):
            nested_policy = {}

        value = (
            root_policy.get("hard_block_penalty")
            if root_policy.get("hard_block_penalty") is not None
            else nested_policy.get("hard_block_penalty")
        )
        if value is None:
            value = root_policy.get("max_penalty", 0.45)

        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.45

    def _keyword_hits_in_text(self, text: str, keywords: List[Any]) -> List[str]:
        normalized_text = self._normalize_rule_text(text)
        hits: List[str] = []

        for keyword in keywords or []:
            kw = self._normalize_rule_text(keyword)
            if kw and kw in normalized_text:
                hits.append(kw)

        return hits

    def _get_dessert_penalty_for_meal_type(self, meal_type: str) -> tuple[float, int]:
        rules = self._rules_get(
            "recipe_quality_rules",
            "dessert_detection",
            default={},
        )
        if not isinstance(rules, dict) or not rules.get("enabled", True):
            return 0.0, 0

        meal_type_key = self._normalize_rule_token(meal_type)
        penalties = rules.get("penalties", {}) or {}
        negative_hits = rules.get("negative_hits", {}) or {}

        penalty = float(
            penalties.get(
                meal_type_key,
                penalties.get("default", 0.0),
            )
            or 0.0
        )
        hits = int(
            negative_hits.get(
                meal_type_key,
                negative_hits.get("default", 0),
            )
            or 0
        )

        return penalty, hits

    def _get_missing_main_carb_penalty(
        self,
        meal_type: str,
        goal: Optional[str] = None,
    ) -> tuple[float, int]:
        rules = self._rules_get(
            "recipe_quality_rules",
            "missing_main_carb",
            default={},
        )
        if not isinstance(rules, dict) or not rules.get("enabled", True):
            return 0.0, 0

        meal_type_key = self._normalize_rule_token(meal_type)
        applies_to = {
            self._normalize_rule_token(x)
            for x in rules.get("applies_to_meal_types", []) or []
        }

        if meal_type_key not in applies_to:
            return 0.0, 0

        goal_key = self._normalize_goal(goal or getattr(self, "_current_goal", "balanced"))
        penalties = rules.get("penalties", {}) or {}

        penalty = float(
            penalties.get(
                goal_key,
                penalties.get("default", 0.0),
            )
            or 0.0
        )
        negative_hits = int(rules.get("negative_hits", 1) or 1)

        return penalty, negative_hits

    # ==============================
    # PUBLIC API
    # ==============================

    def build_plan(
        self,
        user_profile,
        days: int = 7,
        candidate_limit: int = 80,
        explain_with_llm: bool = True,
    ) -> Dict[str, Any]:
        goal = self._normalize_goal(getattr(user_profile, "goal", "balanced"))
        self._current_goal = goal
        meals_per_day = self._clamp_meals_per_day(
            getattr(user_profile, "meals_per_day", 3)
        )

        target_calories = self._get_target_calories(user_profile, goal)
        macro_targets = self._get_macro_targets(target_calories, goal, user_profile)

        candidates = self._fetch_candidates(user_profile, candidate_limit)

        if not candidates:
            return {
                "status": "empty",
                "plan_type": goal,
                "target_calories": target_calories,
                "meals_per_day": meals_per_day,
                "macro_targets": macro_targets,
                "plan": [],
                "message": "No candidates found for meal planning.",
            }

        simulated_profile = deepcopy(user_profile)
        full_plan: List[Dict[str, Any]] = []
        recent_recipe_names = self._recent_recipe_names_from_profile(simulated_profile)

        for day_idx in range(max(1, int(days))):
            day_result = self._build_day(
                day_number=day_idx + 1,
                user_profile=simulated_profile,
                candidates=candidates,
                target_calories=target_calories,
                macro_targets=macro_targets,
                meals_per_day=meals_per_day,
                recent_recipe_names=recent_recipe_names,
            )
            full_plan.append(day_result)

            # В историю профиля пишем только имена, потому что UserProfile.add_meal ожидает list[str].
            # if hasattr(simulated_profile, "add_meal"):
            #   for meal in day_result["meals"]:
            #        simulated_profile.add_meal(self._ingredient_names(meal["ingredients"]))

        plan = {
            "status": "ok",
            "plan_type": goal,
            "target_calories": target_calories,
            "meals_per_day": meals_per_day,
            "macro_targets": macro_targets,
            "plan": full_plan,
        }

        if explain_with_llm and self.llm is not None:
            plan["llm_review"] = self._llm_review(plan, user_profile)
            plan["llm_explanation"] = self._llm_explain(plan, user_profile)

        return plan

    # ==============================
    # TARGETS
    # ==============================

    def _normalize_goal(self, goal: Optional[str]) -> str:
        if not goal:
            return "balanced"
        return self.GOAL_ALIASES.get(str(goal).strip().lower(), "balanced")

    def _clamp_meals_per_day(self, meals_per_day: int) -> int:
        try:
            meals = int(meals_per_day)
        except Exception:
            meals = 3
        return max(1, min(6, meals))

    def _get_target_calories(self, user_profile, goal: str) -> int:
        if getattr(user_profile, "target_calories", None):
            return int(user_profile.target_calories)

        age = getattr(user_profile, "age", None)
        sex = getattr(user_profile, "sex", None)
        height_cm = getattr(user_profile, "height_cm", None)
        weight_kg = getattr(user_profile, "weight_kg", None)
        activity_level = getattr(user_profile, "activity_level", "moderate")

        if None in (age, sex, height_cm, weight_kg):
            return 2200 if goal == "balanced" else 2000

        try:
            age = float(age)
            height_cm = float(height_cm)
            weight_kg = float(weight_kg)
        except Exception:
            return 2200 if goal == "balanced" else 2000

        if str(sex).lower() == "male":
            bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
        else:
            bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

        multipliers = {
            "sedentary": 1.2,
            "light": 1.375,
            "moderate": 1.55,
            "active": 1.725,
            "very_active": 1.9,
        }

        tdee = bmr * multipliers.get(str(activity_level).lower(), 1.55)

        if goal == "weight_loss":
            return max(1200, int(tdee - 450))
        if goal == "muscle_gain":
            return int(tdee + 300)
        return int(tdee)

    def _get_macro_targets(self, calories: int, goal: str, user_profile) -> Dict[str, float]:
        """
        Если UserProfile уже содержит protein_target_g/fat_target_g — используем их.
        Иначе считаем профессиональный fallback через вес пользователя.
        """

        protein = getattr(user_profile, "protein_target_g", None)
        fat = getattr(user_profile, "fat_target_g", None)

        if protein and fat:
            protein = float(protein)
            fat = float(fat)
        else:
            weight = getattr(user_profile, "weight_kg", None)

            if weight:
                try:
                    weight = float(weight)
                except Exception:
                    weight = None

            if weight:
                if goal == "weight_loss":
                    protein = weight * 2.0
                    fat = weight * 0.75
                elif goal == "muscle_gain":
                    protein = weight * 1.8
                    fat = weight * 0.9
                else:
                    protein = weight * 1.6
                    fat = weight * 0.8

                # Не даём жирам съесть слишком большую часть калорий.
                max_fat_by_calories = (calories * 0.35) / 9
                min_fat_by_calories = (calories * 0.20) / 9
                fat = max(min_fat_by_calories, min(fat, max_fat_by_calories))
            else:
                protein = (calories * 0.28) / 4
                fat = (calories * 0.27) / 9

        remaining = calories - (protein * 4 + fat * 9)
        carbs = max(0.0, remaining / 4)

        # Минимальный floor для обычного питания. Для keto/low_carb может быть переопределён.
        carb_limit = getattr(user_profile, "carb_limit_g", None)
        if carb_limit:
            carbs = min(carbs, float(carb_limit))
        elif goal != "weight_loss":
            carbs = max(50.0, carbs)

        return {
            "protein_g": round(protein, 1),
            "fat_g": round(fat, 1),
            "carbs_g": round(carbs, 1),
        }

    def _meal_weights(self, meals_per_day: int, goal: str) -> List[float]:
        if meals_per_day == 1:
            return [1.0]
        if meals_per_day == 2:
            return [0.55, 0.45]
        if meals_per_day == 3:
            return [0.30, 0.40, 0.30]
        if meals_per_day == 4:
            return [0.22, 0.30, 0.28, 0.20]
        if meals_per_day == 5:
            return [0.18, 0.18, 0.28, 0.16, 0.20]
        return [0.15, 0.12, 0.20, 0.13, 0.12, 0.28]

    def _meal_type_for_slot(self, slot_idx: int, meals_per_day: int) -> str:
        mapping = self.meal_planner_rules.get("meal_type_by_meals_per_day", {})
        sequence = mapping.get(str(meals_per_day))

        if isinstance(sequence, list) and 0 <= slot_idx < len(sequence):
            return str(sequence[slot_idx])

        fallback = {
            1: ["lunch"],
            2: ["lunch", "dinner"],
            3: ["breakfast", "lunch", "dinner"],
            4: ["breakfast", "lunch", "snack", "dinner"],
            5: ["breakfast", "snack", "lunch", "snack", "dinner"],
            6: ["breakfast", "snack", "lunch", "snack", "snack", "dinner"],
        }

        return fallback.get(meals_per_day, fallback[3])[slot_idx]

    def _slot_macro_targets(self, macro_targets: Dict[str, float], weight: float) -> Dict[str, float]:
        return {
            "protein_g": round(float(macro_targets.get("protein_g", 0)) * weight, 1),
            "fat_g": round(float(macro_targets.get("fat_g", 0)) * weight, 1),
            "carbs_g": round(float(macro_targets.get("carbs_g", 0)) * weight, 1),
        }

    # ==============================
    # CANDIDATES
    # ==============================

    def _build_search_query(self, user_profile) -> str:
        goal = self._normalize_goal(getattr(user_profile, "goal", "balanced"))

        if goal == "weight_loss":
            parts = [
                "healthy high protein meal",
                "lean protein vegetables",
                "low calorie main dish",
            ]
        elif goal == "muscle_gain":
            parts = [
                "high protein main dish",
                "meat carbs meal",
                "muscle gain lunch dinner",
            ]
        else:
            parts = [
                "healthy main dish",
                "protein carbs vegetables",
                "lunch dinner meal",
            ]

        preferred = getattr(user_profile, "preferred_ingredients", None) or []
        if preferred:
            parts.extend(preferred[:5])

        return " ".join(str(p) for p in parts if p)

    def _build_slot_search_query(
        self,
        user_profile,
        goal: str,
        meal_type: str,
        slot_target_calories: float,
        slot_target_macros: Dict[str, float],
        used_main_carbs: Optional[List[str]] = None,
    ) -> str:
        """
        PROD slot query builder.

        Все фразы берутся из meal_planner_rules.json:
        slot_query_rules.base_terms
        slot_query_rules.nutrition_terms
        slot_query_rules.macro_terms
        slot_query_rules.macro_term_text
        """
        rules = self._rules_get("slot_query_rules", default={})
        if not isinstance(rules, dict):
            rules = {}

        goal = self._normalize_goal(goal)
        meal_type_key = self._normalize_rule_token(meal_type)

        parts: List[str] = []

        base_terms = rules.get("base_terms", {}) or {}
        nutrition_terms = rules.get("nutrition_terms", {}) or {}

        base_text = base_terms.get(meal_type_key, meal_type_key)
        nutrition_text = nutrition_terms.get(goal, goal)

        if base_text:
            parts.append(str(base_text))
        if nutrition_text:
            parts.append(str(nutrition_text))

        macro_rules = rules.get("macro_terms", {}) or {}
        macro_text = rules.get("macro_term_text", {}) or {}

        protein_target = float(slot_target_macros.get("protein_g", 0.0) or 0.0)
        carbs_target = float(slot_target_macros.get("carbs_g", 0.0) or 0.0)
        fat_target = float(slot_target_macros.get("fat_g", 0.0) or 0.0)

        def add_terms(key: str) -> None:
            value = macro_text.get(key, [])
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(x) for x in value if str(x).strip())

        if protein_target >= float(macro_rules.get("high_protein_min_g", 30) or 30):
            add_terms("high_protein")
        elif protein_target >= float(macro_rules.get("protein_min_g", 20) or 20):
            add_terms("protein")

        if carbs_target >= float(macro_rules.get("balanced_carbs_min_g", 50) or 50):
            add_terms("balanced_carbs")
        elif carbs_target <= float(macro_rules.get("low_carb_max_g", 30) or 30):
            add_terms("low_carb")

        if fat_target <= float(macro_rules.get("moderate_fat_max_g", 20) or 20):
            add_terms("moderate_fat")

        if used_main_carbs:
            diversity_terms = rules.get("carb_diversity_terms", "")
            if isinstance(diversity_terms, list):
                parts.extend(str(x) for x in diversity_terms if str(x).strip())
            elif diversity_terms:
                parts.append(str(diversity_terms))

        preferred_limit = int(rules.get("preferred_ingredients_limit", 3) or 3)
        preferred = getattr(user_profile, "preferred_ingredients", None) or []
        if preferred:
            parts.extend([str(x) for x in preferred[:preferred_limit]])

        clean_parts: List[str] = []
        seen = set()

        for part in parts:
            part = str(part).strip()
            if not part:
                continue
            key = part.lower()
            if key in seen:
                continue
            seen.add(key)
            clean_parts.append(part)

        return " ".join(clean_parts)

    def _fetch_candidates(self, user_profile, candidate_limit: int) -> List[Dict[str, Any]]:
        query = self._build_search_query(user_profile)

        # Важно: FAISS сейчас шумный, поэтому берём больше,
        # а потом rerank-фильтруем под meal planning.
        search_limit = max(candidate_limit * 3, 180)

        try:
            raw = self.recipe_search.search(query, top_k=search_limit)
        except TypeError:
            raw = self.recipe_search.search(query)
        except Exception as exc:
            logger.warning(f"Recipe search failed: {exc}")
            raw = []

        if isinstance(raw, dict):
            if "recipes" in raw and isinstance(raw["recipes"], list):
                raw = raw["recipes"]
            else:
                raw = list(raw.values())

        if not isinstance(raw, list):
            return []

        candidates = []

        for item in raw:
            norm = self._normalize_recipe(item)
            if norm:
                candidates.append(norm)

        if self.recipe_reranker is not None:
            candidates = self.recipe_reranker.rerank(
                candidates,
                user_profile=user_profile,
                limit=candidate_limit,
            )
        else:
            candidates = candidates[:candidate_limit]

        return candidates

    def _fetch_slot_candidates(
        self,
        user_profile,
        goal: str,
        meal_type: str,
        slot_target_calories: Optional[float] = None,
        slot_target_macros: Optional[Dict[str, float]] = None,
        candidate_limit: int = 80,
        used_main_carbs: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        PROD slot-aware candidate fetch.

        Важно:
        - slot_target_macros теперь optional, чтобы не падали старые тесты/debug-скрипты;
        - если macros не переданы, считаем их из полного дневного target;
        - если старый код случайно передал candidate_limit пятым positional-аргументом,
        не падаем, а корректно восстанавливаем candidate_limit.
        """

        goal = self._normalize_goal(goal)
        self._current_goal = goal
        used_main_carbs = used_main_carbs or []

        # Backward compatibility:
        # _fetch_slot_candidates(profile, goal, meal_type, slot_kcal, candidate_limit)
        if slot_target_macros is not None and not isinstance(slot_target_macros, dict):
            try:
                candidate_limit = int(slot_target_macros)
            except Exception:
                pass
            slot_target_macros = None

        target_calories = self._get_target_calories(user_profile, goal)

        if slot_target_calories is None:
            meals_per_day = self._clamp_meals_per_day(
                getattr(user_profile, "meals_per_day", 3)
            )
            meal_type_sequence = [
                self._meal_type_for_slot(i, meals_per_day)
                for i in range(meals_per_day)
            ]

            try:
                slot_idx = meal_type_sequence.index(meal_type)
            except ValueError:
                slot_idx = 0

            weights = self._meal_weights(meals_per_day, goal)
            slot_target_calories = target_calories * weights[slot_idx]

        if slot_target_macros is None:
            macro_targets = self._get_macro_targets(
                target_calories,
                goal,
                user_profile,
            )
            slot_weight = float(slot_target_calories) / max(float(target_calories), 1.0)
            slot_target_macros = self._slot_macro_targets(
                macro_targets,
                slot_weight,
            )

        query = self._build_slot_search_query(
            user_profile=user_profile,
            goal=goal,
            meal_type=meal_type,
            slot_target_calories=float(slot_target_calories),
            slot_target_macros=slot_target_macros,
            used_main_carbs=used_main_carbs,
        )

        search_limit = max(candidate_limit * 3, 240)

        try:
            raw = self.recipe_search.search(query, top_k=search_limit)
        except TypeError:
            raw = self.recipe_search.search(query)
        except Exception as exc:
            logger.warning(f"Slot recipe search failed: {exc}")
            raw = []

        if isinstance(raw, dict):
            if "recipes" in raw and isinstance(raw["recipes"], list):
                raw = raw["recipes"]
            else:
                raw = list(raw.values())

        if not isinstance(raw, list):
            return []

        candidates = []

        for item in raw:
            norm = self._normalize_recipe(item)
            if norm:
                candidates.append(norm)

        return self._rerank_slot_candidates(
            candidates=candidates,
            meal_type=meal_type,
            used_main_carbs=used_main_carbs,
            candidate_limit=candidate_limit,
        )

    def _normalize_ingredient_name(self, name: str) -> str:
        """
        Приводит ингредиент рецепта к canonical name.

        Примеры:
        chicken_breast -> chicken
        chicken thighs -> chicken
        ground_beef -> beef
        salmon_fillet -> salmon
        spaghetti -> pasta/noodles, если так задано в aliases
        """

        raw = str(name or "").strip().lower()

        if not raw:
            return ""

        normalizer = getattr(self.nutrition_engine, "name_normalizer", None)

        if normalizer is not None:
            try:
                return normalizer.canonical(raw)
            except Exception:
                pass

        return raw.replace("-", "_").replace(" ", "_")

    def _normalize_recipe(self, recipe: Any) -> Optional[Dict[str, Any]]:
        """
        Приводит результат RecipeSearch / запись recipes.json к внутреннему формату.

        Важно для prod:
        - не теряем source;
        - не теряем ingredients_detail/servings/nutrition, если они есть;
        - ingredients остаётся list[str] для текущих scorer/reranker;
        - grams остаются в ingredients_detail, чтобы PortionOptimizer мог их использовать.
        """
        if not isinstance(recipe, dict):
            return None

        raw_ingredients = recipe.get("ingredients", []) or []

        normalized_ingredients: List[str] = []
        original_ingredients: List[str] = []

        for item in raw_ingredients:
            if isinstance(item, str):
                raw_name = item.strip()
            elif isinstance(item, dict):
                raw_name = str(
                    item.get("canonical_name")
                    or item.get("name")
                    or item.get("ingredient")
                    or ""
                ).strip()
            else:
                continue

            if not raw_name:
                continue

            original_ingredients.append(raw_name)

            canonical = self._normalize_ingredient_name(raw_name)
            if canonical:
                normalized_ingredients.append(canonical)

        # Если ingredients пустой, пробуем собрать из ingredients_detail.
        if not normalized_ingredients:
            for item in recipe.get("ingredients_detail", []) or []:
                if not isinstance(item, dict):
                    continue

                raw_name = str(
                    item.get("canonical_name")
                    or item.get("name")
                    or item.get("ingredient")
                    or ""
                ).strip()

                if not raw_name:
                    continue

                original_ingredients.append(raw_name)

                canonical = self._normalize_ingredient_name(raw_name)
                if canonical:
                    normalized_ingredients.append(canonical)

        # Убираем дубли, но сохраняем порядок.
        deduped: List[str] = []
        seen = set()

        for ing in normalized_ingredients:
            if ing not in seen:
                deduped.append(ing)
                seen.add(ing)

        name = (
            recipe.get("name")
            or recipe.get("title")
            or recipe.get("dish_name")
            or "unknown meal"
        )

        try:
            score = float(recipe.get("score", 0.5))
        except (TypeError, ValueError):
            score = 0.5

        normalized: Dict[str, Any] = {
            "name": str(name),
            "ingredients": deduped,
            "raw_ingredients": original_ingredients,
            "instructions": recipe.get("instructions", recipe.get("steps", [])),
            "tags": recipe.get("tags", []),
            "cuisine": recipe.get("cuisine", "generic"),
            "score": score,
            "source": recipe,
        }

        # Сохраняем prod-поля рецепта, не ломая старую структуру.
        passthrough_keys = [
            "id",
            "schema_version",
            "ingredients_detail",
            "servings",
            "serving_model",
            "total_weight_g",
            "serving_weight_g",
            "nutrition",
            "search_profile",
            "diet_tags",
            "allergens",
            "data_quality",
            "practicality",
            "cookware",
            "scaling",
        ]

        for key in passthrough_keys:
            if key in recipe:
                normalized[key] = deepcopy(recipe[key])

        return normalized

    def _normalize_ingredients(self, ingredients: Any) -> List[Ingredient]:
        if not isinstance(ingredients, list):
            return []

        result: List[Ingredient] = []

        for item in ingredients:
            if isinstance(item, str):
                name = item.strip().lower()
                if name:
                    result.append(name)
                continue

            if isinstance(item, dict) and item.get("name"):
                normalized: Dict[str, Any] = {
                    "name": str(item["name"]).strip().lower()
                }

                grams = item.get("grams")
                if grams is None:
                    grams = item.get("amount")
                if grams is None:
                    grams = item.get("weight_g")

                if grams is not None:
                    try:
                        normalized["grams"] = float(grams)
                    except Exception:
                        pass

                state = item.get("state") or item.get("input_state")
                if state:
                    normalized["state"] = str(state).strip().lower()

                # Сохраняем дополнительные поля, если они есть.
                for extra_key in ("unit", "role", "note"):
                    if extra_key in item:
                        normalized[extra_key] = item[extra_key]

                result.append(normalized)

        return result

    # ==============================
    # INGREDIENT HELPERS
    # ==============================

    def _ingredient_name(self, item: Ingredient) -> str:
        if isinstance(item, dict):
            return str(item.get("name", "")).strip().lower()
        return str(item).strip().lower()

    def _ingredient_names(self, ingredients: List[Ingredient]) -> List[str]:
        names = []
        for item in ingredients or []:
            name = self._ingredient_name(item)
            if name:
                names.append(name)
        return names

    def _recipe_signature(self, ingredients: List[Ingredient]) -> str:
        names = {self._ingredient_name(i) for i in ingredients if self._ingredient_name(i)}
        return "|".join(sorted(names))

    def _with_replaced_name(self, item: Ingredient, new_name: str) -> Ingredient:
        new_name = str(new_name).strip().lower()

        if isinstance(item, dict):
            updated = dict(item)
            updated["name"] = new_name
            return updated

        return new_name

    # ==============================
    # NUTRITION
    # ==============================

    def _profile_as_dict(self, user_profile) -> Optional[dict]:
        if user_profile is None:
            return None
        if isinstance(user_profile, dict):
            return user_profile
        return getattr(user_profile, "__dict__", None)

    def _recipe_nutrition(
        self,
        recipe: Dict[str, Any],
        user_profile=None,
        meal_type: str = "lunch",
    ) -> Dict[str, float]:
        nutrition = recipe.get("nutrition")

        if isinstance(nutrition, dict) and nutrition.get("calories") is not None:
            base = {
                "calories": float(nutrition.get("calories", 0)),
                "protein": float(nutrition.get("protein", 0)),
                "fat": float(nutrition.get("fat", 0)),
                "carbs": float(nutrition.get("carbs", 0)),
                "fiber": float(nutrition.get("fiber", 0)),
                "sugar": float(nutrition.get("sugar", 0)),
                "sodium_mg": float(nutrition.get("sodium_mg", 0)),
                "saturated_fat": float(nutrition.get("saturated_fat", 0)),
                "eaten_weight_g": float(nutrition.get("eaten_weight_g", 0)),
                "nutrition_weight_g": float(nutrition.get("nutrition_weight_g", 0)),
                "satiety_score": float(nutrition.get("satiety_score", 0)),
                "category_balance": float(nutrition.get("category_balance", 0.5)),
                "energy_density_kcal_per_g": float(nutrition.get("energy_density_kcal_per_g", 0)),
            }
            return base

        ingredients = recipe.get("ingredients", [])
        base = self.nutrition_engine.calculate(
            ingredients,
            profile=self._profile_as_dict(user_profile),
            meal_type=meal_type,
        )

        servings = recipe.get("servings", 1)
        try:
            servings = max(1.0, float(servings))
        except Exception:
            servings = 1.0

        result: Dict[str, Any] = {}

        for key, value in base.items():
            if isinstance(value, (int, float)):
                if key in self.ABSOLUTE_NUTRITION_KEYS:
                    result[key] = float(value) / servings
                else:
                    # score/ratio поля не делим на servings
                    result[key] = float(value)
            else:
                result[key] = value

        # Гарантируем наличие базовых ключей, чтобы scoring не падал.
        for key in [
            "calories", "protein", "fat", "carbs", "fiber", "sugar",
            "sodium_mg", "saturated_fat", "eaten_weight_g", "nutrition_weight_g",
            "satiety_score", "category_balance", "energy_density_kcal_per_g",
        ]:
            result.setdefault(key, 0.0)

        return result

    # ==============================
    # SCORING
    # ==============================

    def _calorie_fit_score(self, actual: float, target: float) -> float:
        if actual <= 0 or target <= 0:
            return 0.0
        ratio = actual / target
        return exp(-((ratio - 1.0) ** 2) / (2 * 0.22 ** 2))

    def _macro_component_score(self, actual: float, target: float, sigma: float = 0.35) -> float:
        if target <= 0:
            return 1.0
        if actual < 0:
            return 0.0
        ratio = actual / target
        return exp(-((ratio - 1.0) ** 2) / (2 * sigma ** 2))

    def _macro_target_fit_score(
        self,
        meal_nutrition: Dict[str, float],
        slot_macro_targets: Dict[str, float],
    ) -> float:
        p = self._macro_component_score(
            meal_nutrition.get("protein", 0.0),
            slot_macro_targets.get("protein_g", 0.0),
        )
        f = self._macro_component_score(
            meal_nutrition.get("fat", 0.0),
            slot_macro_targets.get("fat_g", 0.0),
        )
        c = self._macro_component_score(
            meal_nutrition.get("carbs", 0.0),
            slot_macro_targets.get("carbs_g", 0.0),
        )
        return clamp((p * 1.15 + f * 0.9 + c) / 3.05)

    def _macro_progress_score(
        self,
        current_totals: Dict[str, float],
        meal_nutrition: Dict[str, float],
        target_macros: Dict[str, float],
    ) -> float:
        def score_component(current, meal, target, over_penalty: float = 1.25):
            if target <= 0:
                return 1.0

            after = current + meal
            before_error = abs(target - current) / target
            after_error = abs(target - after) / target

            score = 1.0 - after_error
            if after_error >= before_error:
                score = 1.0 - (after_error * over_penalty)

            return clamp(score)

        p = score_component(
            current_totals.get("protein", 0.0),
            meal_nutrition.get("protein", 0.0),
            target_macros.get("protein_g", 0.0),
            over_penalty=1.1,
        )
        f = score_component(
            current_totals.get("fat", 0.0),
            meal_nutrition.get("fat", 0.0),
            target_macros.get("fat_g", 0.0),
            over_penalty=1.35,
        )
        c = score_component(
            current_totals.get("carbs", 0.0),
            meal_nutrition.get("carbs", 0.0),
            target_macros.get("carbs_g", 0.0),
            over_penalty=1.2,
        )

        return clamp((p * 1.2 + f + c) / 3.2)

    def _recent_recipe_names_from_profile(self, user_profile) -> List[str]:
        """
        Возвращает историю названий блюд для cooldown внутри multi-day плана.

        Поддерживает:
        - user_profile.recent_recipe_names: ["Chicken Rice Bowl", ...]
        - user_profile.recent_meals: [{"recipe_name": "..."}] / [{"name": "..."}]
        Если у профиля хранится только список ингредиентов, названия восстановить нельзя,
        поэтому fallback будет пустым.
        """
        result: List[str] = []

        direct = getattr(user_profile, "recent_recipe_names", None) or []
        if isinstance(direct, list):
            for item in direct:
                key = self._recipe_history_key(item)
                if key:
                    result.append(key)

        recent_meals = getattr(user_profile, "recent_meals", None) or []
        if isinstance(recent_meals, list):
            for meal in recent_meals:
                if not isinstance(meal, dict):
                    continue

                raw_name = (
                    meal.get("recipe_name")
                    or meal.get("meal_name")
                    or meal.get("name")
                )
                key = self._recipe_history_key(raw_name)
                if key:
                    result.append(key)

        policy = self._recipe_cooldown_policy()
        window = int(policy.get("history_window_meals", 18))
        return result[-max(1, window):]


    def _recipe_history_key(self, value: Any) -> str:
        return (
            str(value or "")
            .lower()
            .strip()
            .replace("_", " ")
            .replace("-", " ")
        )


    def _recipe_cooldown_penalty(
        self,
        recipe: Dict[str, Any],
        recent_recipe_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Штрафует повтор одного и того же блюда на длинном плане.

        Это отдельный слой от ingredient diversity:
        - diversity может пропустить разные блюда с похожими ингредиентами;
        - cooldown запрещает повторять именно тот же рецепт каждые 1–2 дня.
        """
        policy = self._recipe_cooldown_policy()

        if not policy.get("enabled", True):
            return {
                "recipe_repeat_count": 0,
                "recipe_cooldown_penalty": 0.0,
                "recipe_cooldown_hard_block": False,
            }

        current_key = self._recipe_history_key(recipe.get("name"))
        if not current_key:
            return {
                "recipe_repeat_count": 0,
                "recipe_cooldown_penalty": 0.0,
                "recipe_cooldown_hard_block": False,
            }

        window = int(policy.get("history_window_meals", 18))
        history = [
            self._recipe_history_key(x)
            for x in (recent_recipe_names or [])[-max(1, window):]
        ]
        history = [x for x in history if x]

        repeat_count = history.count(current_key)

        if repeat_count <= 0:
            return {
                "recipe_repeat_count": 0,
                "recipe_cooldown_penalty": 0.0,
                "recipe_cooldown_hard_block": False,
            }

        first_penalty = float(policy.get("first_repeat_penalty", 0.34))
        additional_penalty = float(policy.get("additional_repeat_penalty", 0.18))
        max_penalty = float(policy.get("max_penalty", 0.72))
        hard_block_after = int(policy.get("hard_block_after_repeats", 2))

        penalty = min(
            max_penalty,
            first_penalty + max(0, repeat_count - 1) * additional_penalty,
        )

        hard_block = repeat_count >= hard_block_after
        if hard_block:
            penalty = max(penalty, float(policy.get("hard_block_penalty", 0.65)))

        return {
            "recipe_repeat_count": repeat_count,
            "recipe_cooldown_penalty": round(penalty, 4),
            "recipe_cooldown_hard_block": hard_block,
        }


    def _trim_recent_recipe_history(self, recent_recipe_names: List[str]) -> None:
        policy = self._recipe_cooldown_policy()
        window = int(policy.get("history_window_meals", 18))
        keep = max(1, window)

        if len(recent_recipe_names) > keep:
            del recent_recipe_names[:-keep]


    def _day_macro_pressure_penalty(
        self,
        current_totals: Dict[str, float],
        meal_nutrition: Dict[str, float],
        macro_targets: Dict[str, float],
        target_calories: float,
        goal: str,
    ) -> Dict[str, Any]:
        """
        Day-level macro pressure.

        Смысл:
        отдельная порция может быть хорошей для слота, но после добавления к уже
        выбранным блюдам день может улететь по жирам/калориям. Этот штраф давит
        именно на кандидата, который ломает дневной баланс.
        """
        policy = self._day_macro_pressure_policy()

        if not policy.get("enabled", True):
            return {
                "day_macro_pressure_penalty": 0.0,
                "day_fat_after_ratio": 0.0,
                "day_calories_after_ratio": 0.0,
                "day_carbs_after_ratio": 0.0,
                "day_protein_after_ratio": 0.0,
            }

        def ratio_after(total_key: str, meal_key: str, target: float) -> float:
            if target <= 0:
                return 0.0
            return (
                float(current_totals.get(total_key, 0.0) or 0.0)
                + float(meal_nutrition.get(meal_key, 0.0) or 0.0)
            ) / max(float(target), 1e-6)

        calories_ratio = ratio_after("calories", "calories", float(target_calories))
        protein_ratio = ratio_after(
            "protein",
            "protein",
            float(macro_targets.get("protein_g", 0.0) or 0.0),
        )
        fat_ratio = ratio_after(
            "fat",
            "fat",
            float(macro_targets.get("fat_g", 0.0) or 0.0),
        )
        carbs_ratio = ratio_after(
            "carbs",
            "carbs",
            float(macro_targets.get("carbs_g", 0.0) or 0.0),
        )

        fat_soft = float(policy.get("fat_soft_ratio", 1.02))
        fat_hard = float(policy.get("fat_hard_ratio", 1.18))
        fat_max_penalty = float(policy.get("fat_max_penalty", 0.26))

        calorie_soft = float(policy.get("calorie_soft_ratio", 1.04))
        calorie_hard = float(policy.get("calorie_hard_ratio", 1.12))
        calorie_max_penalty = float(policy.get("calorie_max_penalty", 0.10))

        carbs_soft = float(policy.get("carbs_soft_ratio", 1.18))
        carbs_hard = float(policy.get("carbs_hard_ratio", 1.35))
        carbs_max_penalty = float(policy.get("carbs_max_penalty", 0.08))

        protein_soft = float(policy.get("protein_soft_ratio", 1.45))
        protein_hard = float(policy.get("protein_hard_ratio", 1.75))
        protein_max_penalty = float(policy.get("protein_max_penalty", 0.05))

        def over_penalty(ratio: float, soft: float, hard: float, max_penalty: float) -> float:
            if ratio <= soft or max_penalty <= 0:
                return 0.0
            if hard <= soft:
                return max_penalty
            return clamp((ratio - soft) / (hard - soft)) * max_penalty

        fat_penalty = over_penalty(
            fat_ratio,
            fat_soft,
            fat_hard,
            fat_max_penalty,
        )

        # Если жир уже почти исчерпан, дополнительно штрафуем жирную добавку.
        fat_target = float(macro_targets.get("fat_g", 0.0) or 0.0)
        current_fat = float(current_totals.get("fat", 0.0) or 0.0)
        meal_fat = float(meal_nutrition.get("fat", 0.0) or 0.0)
        if fat_target > 0 and current_fat >= fat_target * 0.90:
            add_weight = float(policy.get("fat_addition_when_budget_low_weight", 0.16))
            fat_penalty += min(0.14, (meal_fat / max(fat_target, 1.0)) * add_weight)

        calorie_penalty = over_penalty(
            calories_ratio,
            calorie_soft,
            calorie_hard,
            calorie_max_penalty,
        )
        carbs_penalty = over_penalty(
            carbs_ratio,
            carbs_soft,
            carbs_hard,
            carbs_max_penalty,
        )
        protein_penalty = over_penalty(
            protein_ratio,
            protein_soft,
            protein_hard,
            protein_max_penalty,
        )

        # Для массонабора меньше давим за калории/белок, для похудения сильнее за жиры.
        if goal == "muscle_gain":
            calorie_penalty *= 0.55
            protein_penalty *= 0.35
        elif goal == "weight_loss":
            fat_penalty *= 1.15
            calorie_penalty *= 1.15

        total_penalty = clamp(
            fat_penalty + calorie_penalty + carbs_penalty + protein_penalty,
            0.0,
            float(policy.get("max_total_penalty", 0.38)),
        )

        return {
            "day_macro_pressure_penalty": round(total_penalty, 4),
            "day_fat_after_ratio": round(fat_ratio, 3),
            "day_calories_after_ratio": round(calories_ratio, 3),
            "day_carbs_after_ratio": round(carbs_ratio, 3),
            "day_protein_after_ratio": round(protein_ratio, 3),
            "day_fat_pressure_penalty": round(fat_penalty, 4),
            "day_calorie_pressure_penalty": round(calorie_penalty, 4),
            "day_carbs_pressure_penalty": round(carbs_penalty, 4),
            "day_protein_pressure_penalty": round(protein_penalty, 4),
        }


    def _preference_score(self, ingredient_names: List[str], user_profile) -> float:
        if self.preference_scorer is None:
            return 0.5
        return clamp(float(self.preference_scorer.score(ingredient_names, user_profile)))

    def _diversity_score(self, ingredient_names: List[str], user_profile) -> float:
        if self.diversity_engine is None:
            return 1.0
        return clamp(float(self.diversity_engine.score(ingredient_names, user_profile)))

    def _history_penalty(self, ingredient_names: List[str], user_profile) -> float:
        """
        Штраф за повтор похожих ингредиентов в недавней истории.

        Поддерживает разные форматы recent_meals:
        - [{"ingredients": [...]}]
        - [{"ingredient_names": [...]}]
        - [[...], [...]]
        - ["chicken", "rice"] как очень старый fallback
        """
        recent = getattr(user_profile, "recent_meals", []) or []
        if not recent:
            return 0.0

        current = {
            self._normalize_food_key(i)
            for i in ingredient_names or []
            if str(i).strip()
        }
        if not current:
            return 0.0

        penalty = 0.0

        for meal in recent[-5:]:
            if isinstance(meal, dict):
                raw_past = (
                    meal.get("ingredients")
                    or meal.get("ingredient_names")
                    or meal.get("items")
                    or []
                )
            elif isinstance(meal, list):
                raw_past = meal
            elif isinstance(meal, tuple):
                raw_past = list(meal)
            else:
                raw_past = []

            past = {
                self._normalize_food_key(i)
                for i in raw_past
                if str(i).strip()
            }

            if not past:
                continue

            if current == past:
                penalty += 0.65

            overlap = len(current & past)
            penalty += overlap * 0.03

        return penalty

    def _ingredient_penalty(self, ingredient_names: List[str], user_profile) -> float:
        penalty = 0.0
        disliked = set(i.lower() for i in getattr(user_profile, "disliked_ingredients", []) or [])
        excluded = set(i.lower() for i in getattr(user_profile, "excluded_ingredients", []) or [])

        for ing in ingredient_names:
            if ing in disliked:
                penalty += 0.12
            if ing in excluded:
                penalty += 0.45

        return penalty

    def _goal_bonus(self, nutrition: Dict[str, float], goal: str) -> float:
        calories = max(1.0, float(nutrition.get("calories", 0.0)))
        protein_density = (nutrition.get("protein", 0.0) * 4) / calories
        carbs_density = (nutrition.get("carbs", 0.0) * 4) / calories
        fat_density = (nutrition.get("fat", 0.0) * 9) / calories
        fiber_density = nutrition.get("fiber", 0.0) / max(calories / 100.0, 1.0)

        if goal == "weight_loss":
            return clamp(
                0.48 * protein_density
                + 0.22 * fiber_density
                + 0.18 * (1.0 - fat_density)
                + 0.12 * (1.0 - carbs_density)
            )

        if goal == "muscle_gain":
            return clamp(
                0.42 * protein_density
                + 0.28 * carbs_density
                + 0.15 * (1.0 - fat_density)
                + 0.15
            )

        return clamp(
            0.35 * protein_density
            + 0.25 * carbs_density
            + 0.20 * (1.0 - fat_density)
            + 0.20
        )

    def _score_candidate(
        self,
        recipe: Dict[str, Any],
        user_profile,
        target_calories: int,
        goal: str,
        slot_target_calories: float,
        slot_macro_targets: Dict[str, float],
        current_totals: Dict[str, float],
        macro_targets: Dict[str, float],
        meal_type: str = "lunch",
        recent_recipe_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ingredients = recipe.get("ingredients", [])
        ingredient_names = self._ingredient_names(ingredients)

        optimized = self.portion_optimizer.optimize_recipe(
            recipe=recipe,
            user_profile=user_profile,
            meal_type=meal_type,
            slot_target_calories=slot_target_calories,
            slot_macro_targets=slot_macro_targets,
        )

        recipe = dict(recipe)
        recipe["ingredients"] = optimized["ingredients"]

        ingredients = recipe["ingredients"]
        ingredient_names = self._ingredient_names(ingredients)
        nutrition = optimized["nutrition"]
        portion_score = optimized["portion"]["score"]

        safety = None
        if self.safety_checker is not None:
            safety = self.safety_checker.check(ingredient_names, user_profile)
            if not safety.get("is_safe", False):
                return {
                    "score": -999.0,
                    "reject": True,
                    "reason": safety.get("issues", []),
                    "nutrition": nutrition,
                    "safety": safety,
                }

        protein_target = macro_targets.get("protein_g", 0.0)
        current_protein = current_totals.get("protein", 0.0)
        protein_gap = max(0.0, protein_target - current_protein)
        protein_priority = clamp(protein_gap / max(protein_target, 1.0))

        protein_density_g_per_kcal = nutrition.get("protein", 0.0) / max(
            nutrition.get("calories", 1.0), 1.0
        )
        protein_score = clamp(protein_priority * protein_density_g_per_kcal * 6.0)

        calorie_fit = self._calorie_fit_score(
            nutrition.get("calories", 0.0),
            slot_target_calories,
        )

        calorie_progress = self._calorie_fit_score(
            current_totals.get("calories", 0.0) + nutrition.get("calories", 0.0),
            target_calories,
        )

        macro_progress = self._macro_progress_score(
            current_totals=current_totals,
            meal_nutrition=nutrition,
            target_macros=macro_targets,
        )

        slot_macro_fit = self._macro_target_fit_score(
            meal_nutrition=nutrition,
            slot_macro_targets=slot_macro_targets,
        )

        pref = self._preference_score(ingredient_names, user_profile)
        div = self._diversity_score(ingredient_names, user_profile)
        retrieval = clamp(float(recipe.get("score", 0.5)))
        goal_fit = self._goal_bonus(nutrition, goal)

        meal_type_rule = self._meal_type_rule_score(recipe, meal_type)
        meal_type_fit = meal_type_rule["meal_type_fit"]
        meal_type_penalty = meal_type_rule["meal_type_penalty"]
        meal_type_bonus = meal_type_rule["meal_type_bonus"]

        category_balance = clamp(float(nutrition.get("category_balance", 0.5)))
        satiety_score = clamp(float(nutrition.get("satiety_score", 0.0)) / 10.0)

        history_penalty = self._history_penalty(ingredient_names, user_profile)
        ingredient_penalty = self._ingredient_penalty(ingredient_names, user_profile)

        substitutions_used = recipe.get("substitutions", [])
        substitution_penalty = min(0.25, 0.05 * len(substitutions_used)) if substitutions_used else 0.0

        day_pressure = self._day_macro_pressure_penalty(
            current_totals=current_totals,
            meal_nutrition=nutrition,
            macro_targets=macro_targets,
            target_calories=target_calories,
            goal=goal,
        )
        day_macro_pressure_penalty = float(day_pressure.get("day_macro_pressure_penalty", 0.0))

        recipe_cooldown = self._recipe_cooldown_penalty(
            recipe=recipe,
            recent_recipe_names=recent_recipe_names,
        )
        recipe_cooldown_penalty = float(recipe_cooldown.get("recipe_cooldown_penalty", 0.0))

        final_score = (
              0.12 * calorie_fit
            + 0.07 * meal_type_fit  
            + 0.11 * calorie_progress
            + 0.14 * macro_progress
            + 0.07 * slot_macro_fit
            + 0.07 * protein_score
            + 0.10 * portion_score
            + 0.08 * category_balance
            + 0.06 * satiety_score
            + 0.08 * pref
            + 0.06 * div
            + 0.03 * retrieval
            + 0.06 * goal_fit
            - meal_type_penalty
            - history_penalty
            - ingredient_penalty
            - substitution_penalty
            - day_macro_pressure_penalty
            - recipe_cooldown_penalty
        )

        final_score = clamp(final_score, 0.0, 1.0)

        return {
            "score": final_score,
            "reject": False,
            "nutrition": nutrition,
            "optimized_portion": optimized["portion"],
            "optimized_ingredients": recipe["ingredients"],
            "components": {
                "calorie_fit": round(calorie_fit, 3),
                "calorie_progress": round(calorie_progress, 3),
                "macro_progress": round(macro_progress, 3),
                "slot_macro_fit": round(slot_macro_fit, 3),
                "protein_score": round(protein_score, 3),
                "protein_priority": round(protein_priority, 3),
                "category_balance": round(category_balance, 3),
                "satiety_score": round(satiety_score, 3),
                "preference": round(pref, 3),
                "diversity": round(div, 3),
                "retrieval": round(retrieval, 3),
                "goal_fit": round(goal_fit, 3),
                "history_penalty": round(history_penalty, 3),
                "ingredient_penalty": round(ingredient_penalty, 3),
                "substitution_penalty": round(substitution_penalty, 3),
                "day_macro_pressure_penalty": round(day_macro_pressure_penalty, 3),
                "recipe_cooldown_penalty": round(recipe_cooldown_penalty, 3),
                "recipe_repeat_count": recipe_cooldown.get("recipe_repeat_count", 0),
                "recipe_cooldown_hard_block": recipe_cooldown.get("recipe_cooldown_hard_block", False),
                "day_fat_after_ratio": day_pressure.get("day_fat_after_ratio", 0.0),
                "day_calories_after_ratio": day_pressure.get("day_calories_after_ratio", 0.0),
                "day_carbs_after_ratio": day_pressure.get("day_carbs_after_ratio", 0.0),
                "day_protein_after_ratio": day_pressure.get("day_protein_after_ratio", 0.0),
                "day_fat_pressure_penalty": day_pressure.get("day_fat_pressure_penalty", 0.0),
                "day_calorie_pressure_penalty": day_pressure.get("day_calorie_pressure_penalty", 0.0),
                "day_carbs_pressure_penalty": day_pressure.get("day_carbs_pressure_penalty", 0.0),
                "day_protein_pressure_penalty": day_pressure.get("day_protein_pressure_penalty", 0.0),
                "portion_score": round(portion_score, 3),
                "meal_type_fit": round(meal_type_fit, 3),
                "meal_type_bonus": round(meal_type_bonus, 3),
                "meal_type_penalty": round(meal_type_penalty, 3),
            },
            "safety": safety,
        }

    # ==============================
    # SUBSTITUTIONS
    # ==============================

    def _apply_substitutions_if_needed(
        self,
        ingredients: List[Ingredient],
        user_profile,
        cuisine: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.substitution_engine is None:
            return {
                "ingredients": deepcopy(ingredients),
                "replacements": [],
            }

        # Сначала пробуем новый вариант: substitution_engine умеет dict.
        try:
            result = self.substitution_engine.apply(
                ingredients=deepcopy(ingredients),
                user_profile=user_profile,
                cuisine=cuisine,
            )
            adjusted = result.get("ingredients", ingredients)
            return {
                "ingredients": self._normalize_ingredients(adjusted),
                "replacements": result.get("replacements", []),
            }
        except Exception:
            pass

        # Fallback для старого SubstitutionEngine, который умеет только list[str].
        original_names = self._ingredient_names(ingredients)

        try:
            result = self.substitution_engine.apply(
                ingredients=original_names,
                user_profile=user_profile,
                cuisine=cuisine,
            )
        except Exception as exc:
            logger.warning(f"Substitution failed: {exc}")
            return {
                "ingredients": deepcopy(ingredients),
                "replacements": [],
            }

        replacement_names = result.get("ingredients", original_names)
        replacements = result.get("replacements", [])

        if (
            isinstance(replacement_names, list)
            and len(replacement_names) == len(ingredients)
        ):
            adjusted = [
                self._with_replaced_name(original, new_name)
                for original, new_name in zip(ingredients, replacement_names)
            ]
        else:
            adjusted = self._normalize_ingredients(replacement_names)

        return {
            "ingredients": adjusted,
            "replacements": replacements,
        }

    # ==============================
    # DAY BUILDING
    # ==============================

    def _empty_day_totals(self) -> Dict[str, float]:
        return {key: 0.0 for key in self.DAY_TOTAL_KEYS}

    def _add_nutrition_to_totals(
        self,
        totals: Dict[str, float],
        nutrition: Dict[str, Any],
    ) -> None:
        for key in self.DAY_TOTAL_KEYS:
            totals[key] += float(nutrition.get(key, 0.0) or 0.0)

    def _ingredient_key_for_carb(self, ing: Any) -> str:
        if isinstance(ing, dict):
            name = (
                ing.get("canonical_name")
                or ing.get("name")
                or ing.get("item")
                or ""
            )
        else:
            name = str(ing or "")

        return self._normalize_food_key(name)

    def _ingredient_grams_for_carb(self, ing: Any) -> float:
        if isinstance(ing, dict):
            try:
                return float(ing.get("grams") or ing.get("amount") or 1.0)
            except Exception:
                return 1.0

        return 1.0

    def _detect_main_carb(self, ingredients: List[Any]) -> Optional[str]:
        carb_weights: Dict[str, float] = {}

        for ing in ingredients or []:
            key = self._ingredient_key_for_carb(ing)
            main_carb = self.main_carb_lookup.get(key)

            if not main_carb:
                continue

            grams = self._ingredient_grams_for_carb(ing)
            carb_weights[main_carb] = carb_weights.get(main_carb, 0.0) + grams

        if not carb_weights:
            return None

        return max(carb_weights.items(), key=lambda x: x[1])[0]

    def _recipe_text_for_rules(self, recipe: Dict[str, Any]) -> str:
        """
        Собирает текст рецепта для rule-based проверок:
        meal_type, breakfast/lunch/dinner fit, penalties.
        """
        parts = []

        parts.append(str(recipe.get("name", "")))
        parts.append(str(recipe.get("cuisine", "")))

        for tag in recipe.get("tags", []) or []:
            parts.append(str(tag))

        for ing in recipe.get("ingredients", []) or []:
            if isinstance(ing, dict):
                parts.append(str(ing.get("name", "")))
                parts.append(str(ing.get("canonical_name", "")))
            else:
                parts.append(str(ing))

        source = recipe.get("source", {})
        if isinstance(source, dict):
            parts.append(str(source.get("name", "")))

            for tag in source.get("tags", []) or []:
                parts.append(str(tag))

            for ing in source.get("ingredients", []) or []:
                if isinstance(ing, dict):
                    parts.append(str(ing.get("name", "")))
                    parts.append(str(ing.get("canonical_name", "")))
                else:
                    parts.append(str(ing))

            for detail in source.get("ingredients_detail", []) or []:
                if isinstance(detail, dict):
                    parts.append(str(detail.get("name", "")))
                    parts.append(str(detail.get("canonical_name", "")))
                    parts.append(str(detail.get("role", "")))

        return " ".join(parts).lower().replace("_", " ")

    def _main_carb_repeat_rule(
        self,
        recipe: Dict[str, Any],
        used_main_carbs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Dict-версия проверки повтора основного источника углеводов.
        Используется только в _rerank_slot_candidates.
        Старый _main_carb_repeat_penalty оставляем как float-версию.
        """
        used_main_carbs = used_main_carbs or []

        policy = self.meal_planner_rules.get("main_carb_repeat_policy", {})
        main_carb = self._detect_main_carb(recipe.get("ingredients", []))

        if not policy.get("enabled", True):
            return {
                "main_carb": main_carb,
                "main_carb_repeat_count": 0,
                "main_carb_repeat_penalty": 0.0,
                "main_carb_hard_block": False,
            }

        if not main_carb:
            return {
                "main_carb": None,
                "main_carb_repeat_count": 0,
                "main_carb_repeat_penalty": 0.0,
                "main_carb_hard_block": False,
            }

        repeat_count = used_main_carbs.count(main_carb)

        max_count_per_plan = self._rules_get(
            "recipe_quality_rules",
            "main_carb_repeat",
            "max_count_per_plan",
            default={},
        ) or {}

        if isinstance(max_count_per_plan, dict) and main_carb:
            max_allowed = int(
                max_count_per_plan.get(
                    main_carb,
                    max_count_per_plan.get("default", 999),
                )
                or 999
            )

            if repeat_count >= max_allowed:
                return {
                    "main_carb": main_carb,
                    "main_carb_repeat_count": repeat_count,
                    "main_carb_repeat_penalty": 0.55,
                    "main_carb_hard_block": True,
                    "main_carb_hard_block_reason": "main_carb_plan_limit",
                }

        allow_same = int(policy.get("allow_same_carb_per_day", 1))
        hard_block_after = int(policy.get("hard_block_after_repeats", 3))

        if repeat_count < allow_same:
            penalty = 0.0
            hard_block = False

        elif repeat_count >= hard_block_after:
            penalty = float(policy.get("max_penalty", 0.35))
            hard_block = True

        else:
            first_penalty = float(policy.get("same_carb_first_repeat_penalty", 0.16))
            additional = float(policy.get("same_carb_additional_repeat_penalty", 0.08))
            max_penalty = float(policy.get("max_penalty", 0.35))

            extra_repeats = max(0, repeat_count - allow_same)
            penalty = min(max_penalty, first_penalty + extra_repeats * additional)
            hard_block = False

        return {
            "main_carb": main_carb,
            "main_carb_repeat_count": repeat_count,
            "main_carb_repeat_penalty": round(penalty, 4),
            "main_carb_hard_block": hard_block,
        }

    def _meal_type_rule_score(
        self,
        recipe: Dict[str, Any],
        meal_type: str,
    ) -> Dict[str, Any]:
        """
        PROD rule-based оценка соответствия рецепта типу приема пищи.

        Исправление v4:
        - раньше positive_bonus был жестко ограничен cfg["positive_bonus"],
          поэтому 1 positive hit и 4 positive hits давали одинаковый бонус;
        - теперь есть bonus per hit + max_positive_bonus;
        - возвращаем hit_keywords для debug, но сохраняем старые поля
          positive_hits / negative_hits для совместимости.
        """
        rules = self.meal_planner_rules.get("meal_type_rules", {})
        cfg = rules.get(meal_type) or rules.get("default") or {}

        if not isinstance(cfg, dict) or not cfg:
            return {
                "meal_type_bonus": 0.0,
                "meal_type_penalty": 0.0,
                "meal_type_fit": 0.5,
                "positive_hits": 0,
                "negative_hits": 0,
                "positive_hit_keywords": [],
                "negative_hit_keywords": [],
            }

        text = self._recipe_text_for_rules(recipe)

        positive_keywords = cfg.get("positive_keywords", []) or []
        negative_keywords = cfg.get("negative_keywords", []) or []

        positive_hit_keywords = []
        negative_hit_keywords = []

        for kw in positive_keywords:
            kw_text = str(kw or "").strip().lower().replace("_", " ")
            if kw_text and kw_text in text:
                positive_hit_keywords.append(kw_text)

        for kw in negative_keywords:
            kw_text = str(kw or "").strip().lower().replace("_", " ")
            if kw_text and kw_text in text:
                negative_hit_keywords.append(kw_text)

        positive_hits = len(positive_hit_keywords)
        negative_hits = len(negative_hit_keywords)

        base_fit = float(cfg.get("base_fit", 0.5))

        # Backward compatible:
        # старый JSON мог иметь только "positive_bonus": 0.08.
        # В таком случае считаем это бонусом за hit, а max делаем больше,
        # чтобы 4 совпадения были сильнее 1 совпадения.
        positive_bonus_per_hit = float(
            cfg.get("positive_bonus_per_hit", cfg.get("positive_bonus", 0.05))
        )
        max_positive_bonus = float(
            cfg.get(
                "max_positive_bonus",
                max(positive_bonus_per_hit * 3.0, positive_bonus_per_hit),
            )
        )

        negative_penalty_per_hit = float(
            cfg.get("negative_penalty_per_hit", cfg.get("negative_penalty", 0.12))
        )
        max_negative_penalty = float(cfg.get("max_penalty", 0.30))

        positive_bonus = min(
            max_positive_bonus,
            positive_hits * positive_bonus_per_hit,
        )

        negative_penalty = min(
            max_negative_penalty,
            negative_hits * negative_penalty_per_hit,
        )

        meal_type_fit = clamp(base_fit + positive_bonus - negative_penalty)

        return {
            "meal_type_bonus": round(positive_bonus, 4),
            "meal_type_penalty": round(negative_penalty, 4),
            "meal_type_fit": round(meal_type_fit, 4),
            "positive_hits": positive_hits,
            "negative_hits": negative_hits,
            "positive_hit_keywords": positive_hit_keywords,
            "negative_hit_keywords": negative_hit_keywords,
        }

    def _is_dessert_like_recipe(self, recipe: Dict[str, Any]) -> bool:
        """
        PROD dessert detector.

        Важно:
        - никаких списков в исполняемом коде;
        - все ключевые слова берутся из:
          meal_planner_rules.json -> recipe_quality_rules.dessert_detection.
        """
        rules = self._rules_get(
            "recipe_quality_rules",
            "dessert_detection",
            default={},
        )

        if not isinstance(rules, dict) or not rules.get("enabled", True):
            return False

        text = self._recipe_text_for_rules(recipe)
        name_text = self._normalize_rule_text(recipe.get("name", ""))
        ingredient_names = {
            self._normalize_rule_token(x)
            for x in self._recipe_ingredient_names(recipe)
            if str(x).strip()
        }

        savory_exceptions = rules.get("savory_name_exceptions", []) or []
        if self._keyword_hits_in_text(name_text, savory_exceptions):
            return False

        name_keywords = rules.get("name_keywords", []) or []
        if self._keyword_hits_in_text(name_text, name_keywords):
            return True

        # Если слово спрятано не в name, а в tags/source/name/ingredients.
        if self._keyword_hits_in_text(text, name_keywords):
            return True

        ingredient_keywords = {
            self._normalize_rule_token(x)
            for x in rules.get("ingredient_keywords", []) or []
            if str(x).strip()
        }
        flour_like_ingredients = {
            self._normalize_rule_token(x)
            for x in rules.get("flour_like_ingredients", []) or []
            if str(x).strip()
        }

        min_sweet_hits = int(rules.get("min_sweet_hits_with_flour", 2) or 2)

        sweet_hits = 0
        for ing in ingredient_names:
            if ing in ingredient_keywords:
                sweet_hits += 1
                continue

            if any(keyword and keyword in ing for keyword in ingredient_keywords):
                sweet_hits += 1

        has_flour_like = any(
            ing in flour_like_ingredients
            or any(keyword and keyword in ing for keyword in flour_like_ingredients)
            for ing in ingredient_names
        )

        return sweet_hits >= min_sweet_hits and has_flour_like

    def _rerank_slot_candidates(
        self,
        candidates: List[Dict[str, Any]],
        meal_type: str,
        used_main_carbs: Optional[List[str]] = None,
        candidate_limit: int = 80,
    ) -> List[Dict[str, Any]]:
        """
        PROD rerank после embedding search.

        Здесь не должно быть ручных keyword/list-ов.
        Все списки, группы и штрафы берутся из meal_planner_rules.json.
        """
        reranked: List[Dict[str, Any]] = []

        meal_type_key = self._normalize_rule_token(meal_type)
        used_main_carbs = list(used_main_carbs or [])
        goal = self._normalize_goal(getattr(self, "_current_goal", "balanced"))

        for recipe in candidates:
            item = dict(recipe)

            original_score = float(item.get("score", 0.0) or 0.0)

            meal_type_rule = self._meal_type_rule_score(item, meal_type_key)
            carb_rule = self._main_carb_repeat_rule(item, used_main_carbs)

            meal_type_bonus = float(meal_type_rule.get("meal_type_bonus", 0.0) or 0.0)
            meal_type_penalty = float(meal_type_rule.get("meal_type_penalty", 0.0) or 0.0)
            meal_type_fit = float(meal_type_rule.get("meal_type_fit", 0.5) or 0.5)

            meal_type_positive_hits = int(
                meal_type_rule.get("positive_hits", 0) or 0
            )
            meal_type_negative_hits = int(
                meal_type_rule.get("negative_hits", 0) or 0
            )

            main_carb = carb_rule.get("main_carb")
            if main_carb is not None:
                main_carb = self._normalize_rule_token(main_carb) or None

            main_carb_repeat_count = int(carb_rule.get("main_carb_repeat_count", 0) or 0)
            main_carb_repeat_penalty = float(carb_rule.get("main_carb_repeat_penalty", 0.0) or 0.0)
            main_carb_hard_block = bool(carb_rule.get("main_carb_hard_block", False))
            main_carb_hard_block_penalty = (
                self._main_carb_hard_block_penalty()
                if main_carb_hard_block
                else 0.0
            )

            is_dessert_like = self._is_dessert_like_recipe(item)
            dessert_penalty = 0.0
            dessert_negative_hits = 0

            if is_dessert_like:
                dessert_penalty, dessert_negative_hits = (
                    self._get_dessert_penalty_for_meal_type(meal_type_key)
                )
                meal_type_penalty += dessert_penalty
                meal_type_negative_hits += dessert_negative_hits

            missing_main_carb_penalty = 0.0
            missing_main_carb_negative_hits = 0

            if main_carb is None:
                missing_main_carb_penalty, missing_main_carb_negative_hits = (
                    self._get_missing_main_carb_penalty(
                        meal_type=meal_type_key,
                        goal=goal,
                    )
                )
                meal_type_penalty += missing_main_carb_penalty
                meal_type_negative_hits += missing_main_carb_negative_hits

            rerank_score = (
                original_score
                + meal_type_bonus
                - meal_type_penalty
                - main_carb_repeat_penalty
                - main_carb_hard_block_penalty
            )
            rerank_score = clamp(rerank_score, 0.0, 1.0)

            item["embedding_score"] = round(original_score, 6)
            item["score"] = round(rerank_score, 6)
            item["rerank_score"] = round(rerank_score, 6)

            item["rerank_components"] = {
                "embedding_score": round(original_score, 4),

                "meal_type_fit": round(meal_type_fit, 4),
                "meal_type_bonus": round(meal_type_bonus, 4),
                "meal_type_penalty": round(meal_type_penalty, 4),
                "meal_type_positive_hits": meal_type_positive_hits,
                "meal_type_negative_hits": meal_type_negative_hits,

                "is_dessert_like": bool(is_dessert_like),
                "dessert_penalty": round(dessert_penalty, 4),
                "dessert_negative_hits": dessert_negative_hits,

                "main_carb": main_carb,
                "main_carb_repeat_count": main_carb_repeat_count,
                "main_carb_repeat_penalty": round(main_carb_repeat_penalty, 4),
                "main_carb_hard_block": main_carb_hard_block,
                "main_carb_hard_block_penalty": round(main_carb_hard_block_penalty, 4),

                "missing_main_carb_penalty": round(missing_main_carb_penalty, 4),
                "missing_main_carb_negative_hits": missing_main_carb_negative_hits,
            }

            reranked.append(item)

        reranked.sort(
            key=lambda x: float(x.get("rerank_score", x.get("score", 0.0)) or 0.0),
            reverse=True,
        )
        return reranked[:candidate_limit]

    def _main_carb_repeat_penalty(
        self,
        ingredients: List[Any],
        used_main_carbs: List[str],
    ) -> float:
        policy = self.meal_planner_rules.get("main_carb_repeat_policy", {})

        if not policy.get("enabled", True):
            return 0.0

        main_carb = self._detect_main_carb(ingredients)
        if not main_carb:
            return 0.0

        repeat_count = used_main_carbs.count(main_carb)

        allowed = int(policy.get("allow_same_carb_per_day", 1))
        if repeat_count < allowed:
            return 0.0

        hard_block_after = int(policy.get("hard_block_after_repeats", 3))
        if repeat_count >= hard_block_after:
            return float(policy.get("max_penalty", 0.35))

        first = float(policy.get("same_carb_first_repeat_penalty", 0.16))
        additional = float(policy.get("same_carb_additional_repeat_penalty", 0.08))
        max_penalty = float(policy.get("max_penalty", 0.35))

        penalty = first + max(0, repeat_count - allowed) * additional
        return min(max_penalty, penalty)

    def _meal_type_by_slot(self, slot_idx: int, meals_per_day: int) -> str:
        """
        Backward-compatible alias.

        Основная логика живёт в _meal_type_for_slot(), потому что она читает
        meal_type_by_meals_per_day из meal_planner_rules.json.
        """
        return self._meal_type_for_slot(slot_idx, meals_per_day)


    def _prefilter_candidates_for_slot(
        self,
        candidates: List[Dict[str, Any]],
        meal_type: str,
        user_profile,
        selected_signatures: set,
        used_main_carbs: set,
        limit: int = 12,
    ) -> List[Dict[str, Any]]:
        scored = []

        for recipe in candidates:
            ingredients = self._recipe_ingredient_names(recipe)
            signature = self._recipe_signature(ingredients)

            if signature in selected_signatures:
                continue

            if self._cheap_restriction_block(ingredients, user_profile):
                continue

            cheap_score = self._cheap_slot_score(
                recipe=recipe,
                ingredients=ingredients,
                meal_type=meal_type,
                used_main_carbs=used_main_carbs,
                user_profile=user_profile,
            )

            scored.append((cheap_score, recipe))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [recipe for _, recipe in scored[:max(1, int(limit))]]


    def _recipe_ingredient_names(self, recipe: Dict[str, Any]) -> List[str]:
        result = []

        for item in recipe.get("ingredients", []):
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get("canonical_name") or item.get("name")
            else:
                continue

            if name:
                result.append(str(name).strip().lower())

        if result:
            return result

        source = recipe.get("source", {})
        if isinstance(source, dict):
            for item in source.get("ingredients_detail", []):
                if isinstance(item, dict):
                    name = item.get("canonical_name") or item.get("name")
                    if name:
                        result.append(str(name).strip().lower())

        return result


    def _cheap_restriction_block(self, ingredients: List[str], user_profile) -> bool:
        """
        Быстрый блок до дорогой оптимизации порций.

        Проверяет excluded/allergies exact-match даже если safety_checker не передан.
        Категорийные аллергены всё равно лучше обрабатываются SafetyChecker.
        """
        normalized_ingredients = {
            self._normalize_food_key(x)
            for x in ingredients or []
            if str(x).strip()
        }

        excluded = {
            self._normalize_food_key(x)
            for x in getattr(user_profile, "excluded_ingredients", []) or []
            if str(x).strip()
        }

        allergies = {
            self._normalize_food_key(x)
            for x in getattr(user_profile, "allergies", []) or []
            if str(x).strip()
        }

        if normalized_ingredients & excluded:
            return True

        if normalized_ingredients & allergies:
            return True

        if self.safety_checker is not None:
            safety = self.safety_checker.check(list(normalized_ingredients), user_profile)
            if isinstance(safety, dict) and not safety.get("is_safe", True):
                return True

        return False


    def _cheap_slot_score(
        self,
        recipe: Dict[str, Any],
        ingredients: List[str],
        meal_type: str,
        used_main_carbs: set,
        user_profile,
    ) -> float:
        """
        Быстрый prefilter score перед дорогой оптимизацией порций.

        В prod-версии не содержит ручных списков.
        Использует:
        - recipe_quality_rules.cheap_scoring
        - recipe_quality_rules.meal_type_groups
        - meal_type_rules
        - main_carb_groups
        """
        cheap_cfg = self._rules_get(
            "recipe_quality_rules",
            "cheap_scoring",
            default={},
        )
        if not isinstance(cheap_cfg, dict):
            cheap_cfg = {}

        meal_type_key = self._normalize_rule_token(meal_type)
        score = 0.0

        embedding_weight = float(cheap_cfg.get("embedding_weight", 0.35) or 0.35)
        preference_weight = float(cheap_cfg.get("preference_weight", 0.20) or 0.20)
        fallback_preference = float(cheap_cfg.get("fallback_preference_score", 0.10) or 0.10)
        meal_type_fit_weight = float(cheap_cfg.get("meal_type_fit_weight", 0.30) or 0.30)

        try:
            score += float(recipe.get("score", 0.0) or 0.0) * embedding_weight
        except (TypeError, ValueError):
            pass

        if self.preference_scorer is not None:
            try:
                score += float(self.preference_scorer.score(ingredients, user_profile)) * preference_weight
            except Exception:
                score += fallback_preference
        else:
            score += fallback_preference

        score += self._cheap_meal_type_fit(
            name=str(recipe.get("name", "") or ""),
            tags={str(t).lower() for t in recipe.get("tags", []) or []},
            ingredients=ingredients,
            meal_type=meal_type_key,
        ) * meal_type_fit_weight

        main_carb = self._cheap_main_carb(ingredients)
        used_main_carbs_norm = {
            self._normalize_rule_token(x)
            for x in used_main_carbs or set()
            if str(x).strip()
        }

        if main_carb and main_carb in used_main_carbs_norm:
            score -= float(cheap_cfg.get("main_carb_repeat_penalty", 0.25) or 0.25)

        strict_main_meals = self._meal_type_group_set("strict_main_meals")

        is_dessert = self._is_dessert_like_recipe(recipe)

        if meal_type_key in strict_main_meals and is_dessert:
            score -= float(cheap_cfg.get("dessert_main_meal_penalty", 0.65) or 0.65)

        if meal_type_key in strict_main_meals:
            text = self._recipe_text_for_rules(recipe)
            breakfast_signal_keywords = cheap_cfg.get("breakfast_signal_keywords", [])
            breakfast_signal_hits = self._keyword_hits_in_text(text, breakfast_signal_keywords)
            if breakfast_signal_hits:
                score -= float(cheap_cfg.get("breakfast_in_strict_main_meal_penalty", 0.70) or 0.70)

        if meal_type_key == "breakfast":
            meal_type_rule = self._meal_type_rule_score(recipe, meal_type_key)
            positive_hits = int(meal_type_rule.get("positive_hits", 0) or 0)
            negative_hits = int(meal_type_rule.get("negative_hits", 0) or 0)
            if negative_hits > 0 and positive_hits <= 0:
                score -= float(cheap_cfg.get("breakfast_heavy_negative_penalty", 0.85) or 0.85)

        return clamp(score, 0.0, 1.0)


    def _cheap_meal_type_fit(
        self,
        name: str,
        tags: set,
        ingredients: List[str],
        meal_type: str,
    ) -> float:
        """
        Быстрая оценка соответствия типу приема пищи.
        Работает через meal_type_rules, без hard-coded списков.
        """
        pseudo_recipe = {
            "name": name,
            "tags": list(tags or []),
            "ingredients": ingredients or [],
        }
        rule = self._meal_type_rule_score(pseudo_recipe, self._normalize_rule_token(meal_type))
        return clamp(float(rule.get("meal_type_fit", 0.5) or 0.5))


    def _cheap_main_carb(self, ingredients: List[str]) -> Optional[str]:
        """
        Быстрое определение main carb через main_carb_groups.
        Никаких локальных carb_groups в коде.
        """
        return self._detect_main_carb(ingredients or [])

    def _candidate_quality_tier(self, scored: dict, slot_idx: int) -> tuple[str, str]:
        """
        PROD staged quality gate.

        Возвращает:
        - "normal"    — хороший кандидат
        - "relaxed"   — не идеальный, но можно использовать, если normal нет
        - "emergency" — крайний fallback, чтобы не оставить слот пустым
        - "blocked"   — нельзя брать вообще
        """
        policy = self._selection_quality_policy()

        if not isinstance(policy, dict) or not policy.get("enabled", True):
            return "normal", ""

        components = scored.get("components", {}) or {}

        final_score = float(scored.get("score", 0.0) or 0.0)
        portion_score = float(components.get("portion_score", 0.0) or 0.0)
        retrieval = float(components.get("retrieval", 0.0) or 0.0)
        slot_macro_fit = float(components.get("slot_macro_fit", 0.0) or 0.0)

        recipe_repeat_count = int(
            components.get(
                "recipe_repeat_count",
                components.get("same_recipe_count", 0),
            )
            or 0
        )

        history_penalty = float(components.get("history_penalty", 0.0) or 0.0)
        cooldown_penalty = float(components.get("recipe_cooldown_penalty", 0.0) or 0.0)
        diversity = float(components.get("diversity", 1.0) or 0.0)

        issues = scored.get("issues", []) or []
        if policy.get("emergency_never_allow_safety_issues", True) and issues:
            return "blocked", "safety_issues"

        normal_min_final_score = float(policy.get("normal_min_final_score", 0.50))
        relaxed_min_final_score = float(policy.get("relaxed_min_final_score", 0.34))
        emergency_min_final_score = float(policy.get("emergency_min_final_score", -0.10))

        normal_min_portion = float(policy.get("normal_min_portion_score", 0.65))
        relaxed_min_portion = float(policy.get("relaxed_min_portion_score", 0.55))
        emergency_min_portion = float(policy.get("emergency_min_portion_score", 0.72))

        normal_min_slot_macro = float(policy.get("normal_min_slot_macro_fit", 0.62))
        relaxed_min_slot_macro = float(policy.get("relaxed_min_slot_macro_fit", 0.50))
        emergency_min_slot_macro = float(policy.get("emergency_min_slot_macro_fit", 0.35))

        normal_max_history = float(policy.get("normal_max_history_penalty", 0.20))
        relaxed_max_history = float(policy.get("relaxed_max_history_penalty", 0.35))
        emergency_max_history = float(policy.get("emergency_max_history_penalty", 0.60))

        normal_max_cooldown = float(policy.get("normal_max_recipe_cooldown_penalty", 0.32))
        relaxed_max_cooldown = float(policy.get("relaxed_max_recipe_cooldown_penalty", 0.48))
        emergency_max_cooldown = float(policy.get("emergency_max_recipe_cooldown_penalty", 0.75))

        normal_min_diversity = float(policy.get("normal_min_diversity", 0.05))
        relaxed_min_diversity = float(policy.get("relaxed_min_diversity", 0.0))

        normal_max_repeat = int(policy.get("normal_max_recipe_repeat_count", 0))
        relaxed_max_repeat = int(policy.get("relaxed_max_recipe_repeat_count", 1))
        emergency_max_repeat = int(policy.get("emergency_max_recipe_repeat_count", 2))

        emergency_min_retrieval = float(policy.get("emergency_min_retrieval", 0.25))

        if (
            final_score >= normal_min_final_score
            and history_penalty <= normal_max_history
            and cooldown_penalty <= normal_max_cooldown
            and diversity >= normal_min_diversity
            and portion_score >= normal_min_portion
            and slot_macro_fit >= normal_min_slot_macro
            and recipe_repeat_count <= normal_max_repeat
        ):
            return "normal", ""

        normal_high_quality_enabled = bool(
            policy.get("normal_high_quality_rescue_enabled", True)
        )

        normal_high_quality_min_final = float(
            policy.get("normal_high_quality_min_final_score", 0.45)
        )
        normal_high_quality_min_portion = float(
            policy.get("normal_high_quality_min_portion_score", 0.82)
        )
        normal_high_quality_min_macro = float(
            policy.get("normal_high_quality_min_slot_macro_fit", 0.74)
        )
        normal_high_quality_max_repeat = int(
            policy.get("normal_high_quality_max_recipe_repeat_count", 1)
        )
        normal_high_quality_reason = str(
            policy.get("normal_high_quality_reason", "normal_high_quality_rescue")
        )

        if (
            normal_high_quality_enabled
            and final_score >= normal_high_quality_min_final
            and portion_score >= normal_high_quality_min_portion
            and slot_macro_fit >= normal_high_quality_min_macro
            and recipe_repeat_count <= normal_high_quality_max_repeat
            and not bool(components.get("recipe_cooldown_hard_block", False))
            and not bool(components.get("macro_hard_block", False))
            and not bool(components.get("main_carb_hard_block", False))
        ):
            return "normal", normal_high_quality_reason

        if (
            final_score >= relaxed_min_final_score
            and history_penalty <= relaxed_max_history
            and cooldown_penalty <= relaxed_max_cooldown
            and diversity >= relaxed_min_diversity
            and portion_score >= relaxed_min_portion
            and slot_macro_fit >= relaxed_min_slot_macro
            and recipe_repeat_count <= relaxed_max_repeat
        ):
            return "relaxed", "relaxed_quality"

        high_quality_relaxed_min_final = float(
            policy.get("relaxed_high_quality_min_final_score", 0.28)
        )
        high_quality_relaxed_min_portion = float(
            policy.get("relaxed_high_quality_min_portion_score", 0.85)
        )
        high_quality_relaxed_min_macro = float(
            policy.get("relaxed_high_quality_min_slot_macro_fit", 0.75)
        )
        high_quality_relaxed_max_repeat = int(
            policy.get("relaxed_high_quality_max_recipe_repeat_count", 1)
        )

        if (
            final_score >= high_quality_relaxed_min_final
            and portion_score >= high_quality_relaxed_min_portion
            and slot_macro_fit >= high_quality_relaxed_min_macro
            and recipe_repeat_count <= high_quality_relaxed_max_repeat
            and not bool(components.get("recipe_cooldown_hard_block", False))
            and not bool(components.get("macro_hard_block", False))
        ):
            return "relaxed", "relaxed_high_quality_low_score_rescue"

        if recipe_repeat_count > emergency_max_repeat:
            return "blocked", "recipe_repeat_limit"

        if (
            final_score >= emergency_min_final_score
            and history_penalty <= emergency_max_history
            and cooldown_penalty <= emergency_max_cooldown
            and portion_score >= emergency_min_portion
            and retrieval >= emergency_min_retrieval
            and slot_macro_fit >= emergency_min_slot_macro
        ):
            return "emergency", "emergency_quality_fallback"

        return "blocked", "quality_too_low"

    def _low_score_policy(self) -> Dict[str, Any]:
        """
        PROD low-score policy.

        Источник истины: ai/data/meal_planner_rules.json ->
        meal_structure_rules.low_score_policy.

        Политика не должна быть захардкожена в исполняемой логике.
        Fallback нужен только чтобы старые тесты не падали, если JSON ещё
        не обновлён.
        """
        cfg = self._rules_get(
            "meal_structure_rules",
            "low_score_policy",
            default={},
        )

        if not isinstance(cfg, dict):
            cfg = {}

        return {
            "enabled": bool(cfg.get("enabled", True)),
            "threshold": float(cfg.get("threshold", 0.35) or 0.35),
            "score_ceiling": float(cfg.get("score_ceiling", 0.349) or 0.349),
            "apply_only_to_relaxed": bool(cfg.get("apply_only_to_relaxed", True)),
            "reason": str(cfg.get("reason", "low_score_ceiling") or "low_score_ceiling"),
        }

    def _low_score_rescue_policy(self) -> Dict[str, Any]:
        """
        PROD rescue-policy для низких score на длинном плане.

        Сначала читаем вложенный JSON:
            meal_structure_rules.low_score_rescue_policy

        Потом поддерживаем старый root-level fallback:
            low_score_rescue_policy

        threshold/score_ceiling по умолчанию берём из low_score_policy,
        чтобы не было двух независимых источников 0.35 / 0.349.
        """
        cfg = self._rules_get(
            "meal_structure_rules",
            "low_score_rescue_policy",
            default=None,
        )

        if not isinstance(cfg, dict):
            cfg = self.meal_planner_rules.get("low_score_rescue_policy", {})

        if not isinstance(cfg, dict):
            cfg = {}

        low_score_policy = self._low_score_policy()

        return {
            "enabled": bool(cfg.get("enabled", True)),
            "threshold": float(
                cfg.get("threshold", low_score_policy.get("threshold", 0.35))
                or 0.35
            ),
            "critical_threshold": float(cfg.get("critical_threshold", 0.20) or 0.20),
            "score_ceiling": float(
                cfg.get("score_ceiling", low_score_policy.get("score_ceiling", 0.349))
                or 0.349
            ),
            "reason": str(
                cfg.get("reason", low_score_policy.get("reason", "low_score_ceiling"))
                or "low_score_ceiling"
            ),
            "max_boost": float(cfg.get("max_boost", 0.24) or 0.24),

            "relax_history_penalty": float(cfg.get("relax_history_penalty", 0.75) or 0.75),
            "relax_recipe_cooldown_penalty": float(cfg.get("relax_recipe_cooldown_penalty", 0.75) or 0.75),
            "relax_main_carb_repeat_penalty": float(cfg.get("relax_main_carb_repeat_penalty", 0.55) or 0.55),

            # ВАЖНО:
            # Macro pressure нельзя сильно откатывать rescue-режимом,
            # иначе он проталкивает блюда с перелётом по жирам.
            "relax_day_macro_pressure_penalty": float(
                cfg.get("relax_day_macro_pressure_penalty", 0.0) or 0.0
            ),

            "diversity_floor": float(cfg.get("diversity_floor", 0.35) or 0.35),
            "diversity_restore_weight": float(cfg.get("diversity_restore_weight", 0.10) or 0.10),

            "block_if_day_fat_after_ratio_above": float(
                cfg.get("block_if_day_fat_after_ratio_above", 1.18) or 1.18
            ),
            "block_if_day_calories_after_ratio_above": float(
                cfg.get("block_if_day_calories_after_ratio_above", 1.12) or 1.12
            ),
            "block_if_day_macro_pressure_penalty_above": float(
                cfg.get("block_if_day_macro_pressure_penalty_above", 0.22) or 0.22
            ),

            "debug": bool(cfg.get("debug", True)),
        }

    def _apply_low_score_rescue(
        self,
        scored: Dict[str, Any],
        *,
        meal_type: str,
        day_number: int,
        slot_idx: int,
    ) -> Dict[str, Any]:
        """
        Rescue mode для длинных планов.

        Важно:
        - НЕ спасает reject/safety/allergy/excluded.
        - НЕ делает плохую еду хорошей.
        - Только возвращает часть soft-penalties, если система сама себя
          зажала history/cooldown/diversity/main_carb/macro-pressure штрафами.
        """

        policy = self._low_score_rescue_policy()

        if not policy["enabled"]:
            return scored

        if scored.get("reject"):
            return scored

        components = scored.setdefault("components", {})

        original_score = float(scored.get("score", 0.0) or 0.0)
        threshold = float(policy["threshold"])
        
        day_fat_after_ratio = float(components.get("day_fat_after_ratio", 0.0) or 0.0)
        day_calories_after_ratio = float(components.get("day_calories_after_ratio", 0.0) or 0.0)
        day_macro_pressure_penalty = float(components.get("day_macro_pressure_penalty", 0.0) or 0.0)

        if day_fat_after_ratio > policy["block_if_day_fat_after_ratio_above"]:
            components["low_score_rescue_applied"] = False
            components["low_score_rescue_blocked_reason"] = "day_fat_after_ratio"
            components["low_score_rescue_blocked_value"] = round(day_fat_after_ratio, 3)
            return scored

        if day_calories_after_ratio > policy["block_if_day_calories_after_ratio_above"]:
            components["low_score_rescue_applied"] = False
            components["low_score_rescue_blocked_reason"] = "day_calories_after_ratio"
            components["low_score_rescue_blocked_value"] = round(day_calories_after_ratio, 3)
            return scored

        if day_macro_pressure_penalty > policy["block_if_day_macro_pressure_penalty_above"]:
            components["low_score_rescue_applied"] = False
            components["low_score_rescue_blocked_reason"] = "day_macro_pressure_penalty"
            components["low_score_rescue_blocked_value"] = round(day_macro_pressure_penalty, 3)
            return scored

        if original_score >= threshold:
            components.setdefault("low_score_rescue_applied", False)
            return scored

        # Safety/restrictions не ослабляем.
        # Если где-то в твоих компонентах есть сильный restriction/ingredient penalty,
        # rescue не должен проталкивать такой рецепт.
        restriction_penalty = float(components.get("restriction_penalty", 0.0) or 0.0)
        ingredient_penalty = float(components.get("ingredient_penalty", 0.0) or 0.0)

        if restriction_penalty >= 0.5 or ingredient_penalty >= 0.5:
            components["low_score_rescue_applied"] = False
            components["low_score_rescue_blocked_reason"] = "restriction_or_ingredient_penalty"
            return scored

        restored = 0.0

        restored += float(components.get("history_penalty", 0.0) or 0.0) * policy["relax_history_penalty"]
        restored += float(components.get("recipe_cooldown_penalty", 0.0) or 0.0) * policy["relax_recipe_cooldown_penalty"]
        restored += float(components.get("main_carb_repeat_penalty", 0.0) or 0.0) * policy["relax_main_carb_repeat_penalty"]
        restored += float(components.get("day_macro_pressure_penalty", 0.0) or 0.0) * policy["relax_day_macro_pressure_penalty"]

        # Diversity у тебя часто проседает на длинном плане.
        # Это не penalty-поле, поэтому компенсируем часть провала отдельно.
        diversity = float(components.get("diversity", 1.0) or 0.0)
        diversity_floor = policy["diversity_floor"]

        if diversity < diversity_floor:
            restored += (diversity_floor - diversity) * policy["diversity_restore_weight"]

        restored = max(0.0, min(float(policy["max_boost"]), restored))

        raw_rescued_score = original_score + restored

        # Не даём rescue поднимать кандидата выше normal-good зоны.
        # Он должен только спасать low-score слот, а не перебивать реально хорошие варианты.
        score_ceiling = float(policy["score_ceiling"])
        ceiling_applied = raw_rescued_score > score_ceiling
        rescued_score = min(raw_rescued_score, score_ceiling)
        rescued_score = clamp(rescued_score, 0.0, 1.0)

        if rescued_score <= original_score:
            components["low_score_rescue_applied"] = False
            components["low_score_policy_applied"] = False
            return scored

        scored["score"] = rescued_score

        components["low_score_rescue_applied"] = True
        components["low_score_before_rescue"] = round(original_score, 4)
        components["low_score_after_rescue"] = round(rescued_score, 4)
        components["low_score_rescue_boost"] = round(rescued_score - original_score, 4)
        components["low_score_rescue_restored_raw"] = round(restored, 4)
        components["low_score_rescue_threshold"] = threshold
        components["low_score_rescue_critical"] = original_score < float(policy["critical_threshold"])

        # Debug для случаев, когда много блюд получают ровно 0.349.
        # Теперь видно не только capped score, но и честный score до ceiling.
        components["low_score_policy_applied"] = bool(ceiling_applied)
        components["low_score_policy_reason"] = str(policy.get("reason", "low_score_ceiling"))
        components["low_score_policy_score_ceiling"] = round(score_ceiling, 4)
        if ceiling_applied:
            components["score_before_low_score_ceiling"] = round(raw_rescued_score, 4)

        scored["low_score_policy_applied"] = bool(ceiling_applied)
        if ceiling_applied:
            scored["score_before_low_score_ceiling"] = round(raw_rescued_score, 6)

        components["low_score_rescue_context"] = {
            "meal_type": meal_type,
            "day_number": day_number,
            "slot_idx": slot_idx,
        }

        return scored

    def _build_day(
        self,
        day_number: int,
        user_profile,
        candidates: List[Dict[str, Any]],
        target_calories: int,
        macro_targets: Dict[str, float],
        meals_per_day: int,
        recent_recipe_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        goal = self._normalize_goal(getattr(user_profile, "goal", "balanced"))
        weights = self._meal_weights(meals_per_day, goal)

        selected_signatures = set()
        used_main_carbs: List[str] = []
        if recent_recipe_names is None:
            recent_recipe_names = self._recent_recipe_names_from_profile(user_profile)

        meals: List[Dict[str, Any]] = []
        day_totals = self._empty_day_totals()

        base_candidates = list(candidates)

        for slot_idx in range(meals_per_day):
            meal_type = self._meal_type_for_slot(slot_idx, meals_per_day)
            slot_weight = weights[slot_idx]

            slot_target = target_calories * slot_weight
            slot_target_macros = self._slot_macro_targets(
                macro_targets,
                slot_weight,
            )

            # PROD: сначала берём кандидатов именно под текущий слот.
            slot_candidates = self._fetch_slot_candidates(
                user_profile=user_profile,
                goal=goal,
                meal_type=meal_type,
                slot_target_calories=slot_target,
                slot_target_macros=slot_target_macros,
                candidate_limit=max(len(base_candidates), 20),
                used_main_carbs=used_main_carbs,
            )

            # Fallback: если slot search ничего не вернул, не ломаем день.
            if not slot_candidates:
                slot_candidates = base_candidates

            optimized_candidates = self._prefilter_candidates_for_slot(
                candidates=slot_candidates,
                meal_type=meal_type,
                user_profile=user_profile,
                selected_signatures=selected_signatures,
                used_main_carbs=set(used_main_carbs),
                limit=self.max_optimized_candidates_per_slot,
            )

            candidate_pools: Dict[str, List[Dict[str, Any]]] = {
                "normal": [],
                "relaxed": [],
                "emergency": [],
            }
            blocked_candidates_debug: List[Dict[str, Any]] = []

            for recipe in optimized_candidates:
                ingredients = list(recipe.get("ingredients", []))
                signature = self._recipe_signature(ingredients)

                if signature in selected_signatures:
                    continue

                substitution_result = self._apply_substitutions_if_needed(
                    ingredients,
                    user_profile,
                    cuisine=recipe.get("cuisine"),
                )

                adjusted_ingredients = substitution_result["ingredients"]

                temp_recipe = dict(recipe)
                temp_recipe["ingredients"] = adjusted_ingredients
                temp_recipe["substitutions"] = substitution_result["replacements"]

                scored = self._score_candidate(
                    temp_recipe,
                    user_profile=user_profile,
                    target_calories=target_calories,
                    goal=goal,
                    slot_target_calories=slot_target,
                    slot_macro_targets=slot_target_macros,
                    current_totals=day_totals,
                    macro_targets=macro_targets,
                    meal_type=meal_type,
                    recent_recipe_names=recent_recipe_names,
                )

                components = scored.setdefault("components", {})
                if not isinstance(components, dict):
                    scored["components"] = {}
                    components = scored["components"]

                goal_quality = self._rules_get(
                    "goal_quality_rules",
                    goal,
                    default={},
                ) or {}

                protein_gap_penalty = 0.0
                protein_ratio = 0.0

                if bool(goal_quality.get("protein_gap_penalty_enabled", True)):
                    nutrition_for_protein = scored.get("nutrition", {}) or {}
                    if not isinstance(nutrition_for_protein, dict):
                        nutrition_for_protein = {}

                    target_protein = float(
                        slot_target_macros.get(
                            "protein_g",
                            slot_target_macros.get("protein", 0.0),
                        )
                        or 0.0
                    )

                    actual_protein = float(
                        nutrition_for_protein.get(
                            "protein",
                            nutrition_for_protein.get("protein_g", 0.0),
                        )
                        or 0.0
                    )

                    if target_protein > 0:
                        protein_ratio = actual_protein / target_protein

                        min_ratio = float(
                            goal_quality.get("min_slot_protein_ratio", 0.80)
                            or 0.80
                        )

                        penalty_weight = float(
                            goal_quality.get("protein_gap_penalty_weight", 0.20)
                            or 0.20
                        )

                        if protein_ratio < min_ratio:
                            protein_gap_penalty = min(
                                0.22,
                                (min_ratio - protein_ratio) * penalty_weight,
                            )

                            scored["score"] = clamp(
                                float(scored.get("score", 0.0) or 0.0) - protein_gap_penalty,
                                0.0,
                                1.0,
                            )

                components["protein_ratio"] = round(protein_ratio, 4)
                components["protein_gap_penalty"] = round(protein_gap_penalty, 4)

                if scored.get("reject"):
                    components["selection_quality_tier"] = "blocked"
                    components["selection_quality_reason"] = "scoring_reject"
                    blocked_candidates_debug.append({
                        "name": temp_recipe.get("name"),
                        "reason": "scoring_reject",
                    })
                    continue

                day_fat_after_ratio = float(components.get("day_fat_after_ratio", 0.0) or 0.0)
                day_calories_after_ratio = float(components.get("day_calories_after_ratio", 0.0) or 0.0)

                macro_policy = self._day_macro_pressure_policy()

                fat_hard_block_ratio = float(macro_policy.get("fat_hard_block_ratio", 1.22))
                calorie_hard_block_ratio = float(macro_policy.get("calorie_hard_block_ratio", 1.15))
                hard_block_min_slot_idx = int(macro_policy.get("hard_block_min_slot_idx", 1))

                if slot_idx >= hard_block_min_slot_idx:
                    if day_fat_after_ratio > fat_hard_block_ratio:
                        components["macro_hard_block"] = True
                        components["macro_hard_block_reason"] = "day_fat_after_ratio"
                        components["macro_hard_block_value"] = round(day_fat_after_ratio, 3)
                        components["selection_quality_tier"] = "blocked"
                        components["selection_quality_reason"] = "macro_hard_block_day_fat_after_ratio"
                        blocked_candidates_debug.append({
                            "name": temp_recipe.get("name"),
                            "reason": "macro_hard_block_day_fat_after_ratio",
                            "value": round(day_fat_after_ratio, 3),
                        })
                        continue

                    if day_calories_after_ratio > calorie_hard_block_ratio:
                        components["macro_hard_block"] = True
                        components["macro_hard_block_reason"] = "day_calories_after_ratio"
                        components["macro_hard_block_value"] = round(day_calories_after_ratio, 3)
                        components["selection_quality_tier"] = "blocked"
                        components["selection_quality_reason"] = "macro_hard_block_day_calories_after_ratio"
                        blocked_candidates_debug.append({
                            "name": temp_recipe.get("name"),
                            "reason": "macro_hard_block_day_calories_after_ratio",
                            "value": round(day_calories_after_ratio, 3),
                        })
                        continue

                optimized_ingredients_for_penalty = scored.get(
                    "optimized_ingredients",
                    adjusted_ingredients,
                )

                main_carb = self._detect_main_carb(optimized_ingredients_for_penalty)

                carb_repeat_penalty = self._main_carb_repeat_penalty(
                    optimized_ingredients_for_penalty,
                    used_main_carbs,
                )

                if carb_repeat_penalty > 0:
                    scored["score"] = clamp(
                        float(scored["score"]) - carb_repeat_penalty,
                        0.0,
                        1.0,
                    )

                components = scored.setdefault("components", {})
                components["main_carb"] = main_carb
                components["main_carb_repeat_penalty"] = round(
                    carb_repeat_penalty,
                    3,
                )

                missing_main_carb_penalty, missing_main_carb_negative_hits = (
                    self._get_missing_main_carb_penalty(
                        meal_type=meal_type,
                        goal=goal,
                    )
                    if main_carb is None
                    else (0.0, 0)
                )

                if missing_main_carb_penalty > 0:
                    scored["score"] = clamp(
                        float(scored["score"]) - missing_main_carb_penalty,
                        0.0,
                        1.0,
                    )

                components["missing_main_carb_penalty"] = round(
                    missing_main_carb_penalty,
                    3,
                )
                components["missing_main_carb_negative_hits"] = missing_main_carb_negative_hits

                # PROD: rescue mode для длинных планов.
                # Включается только если score стал слишком низким из-за soft-penalties.
                scored = self._apply_low_score_rescue(
                    scored,
                    meal_type=meal_type,
                    day_number=day_number,
                    slot_idx=slot_idx,
                )

                components = scored.setdefault("components", {})

                # PROD staged quality selection:
                # normal > relaxed > emergency. Emergency нужен, чтобы слот не оставался пустым,
                # если кандидат безопасный и имеет нормальную порцию/поиск/макро-fit.
                tier, reason = self._candidate_quality_tier(scored, slot_idx)
                components["selection_quality_tier"] = tier
                components["selection_quality_reason"] = reason

                # Дублируем tier/reason на верхний уровень, чтобы debug_report
                # не зависел от внутренней структуры components.
                scored["selection_tier"] = tier
                scored["selection_tier_reason"] = reason

                if tier == "blocked":
                    components["selection_quality_block"] = True
                    blocked_candidates_debug.append({
                        "name": temp_recipe.get("name"),
                        "reason": reason,
                        "score": round(float(scored.get("score", 0.0) or 0.0), 4),
                    })
                    continue

                policy = self._selection_quality_policy()
                if tier == "emergency" and policy.get("emergency_mark_component", True):
                    components["emergency_fallback_candidate"] = True
                elif tier == "relaxed":
                    components["relaxed_quality_candidate"] = True

                optimized_ingredients = scored.get(
                    "optimized_ingredients",
                    adjusted_ingredients,
                )

                meal_candidate = {
                    "meal_type": meal_type,
                    "target_calories": round(slot_target, 1),
                    "target_macros": {
                        "protein_g": round(slot_target_macros.get("protein_g", 0.0), 1),
                        "fat_g": round(slot_target_macros.get("fat_g", 0.0), 1),
                        "carbs_g": round(slot_target_macros.get("carbs_g", 0.0), 1),
                    },
                    "name": temp_recipe["name"],
                    "ingredients": optimized_ingredients,
                    "portion": scored.get("optimized_portion", {}),
                    "ingredient_names": self._ingredient_names(optimized_ingredients),
                    "nutrition": scored["nutrition"],
                    "score": scored["score"],
                    "selection_tier": scored.get("selection_tier", tier),
                    "selection_tier_reason": scored.get("selection_tier_reason", reason),
                    "score_before_low_score_ceiling": scored.get("score_before_low_score_ceiling"),
                    "low_score_policy_applied": scored.get("low_score_policy_applied", False),
                    "components": components,
                    "warnings": (
                        scored.get("safety", {}).get("warnings", [])
                        if scored.get("safety")
                        else []
                    ),
                    "issues": (
                        scored.get("safety", {}).get("issues", [])
                        if scored.get("safety")
                        else []
                    ),
                    "replacements": substitution_result["replacements"],
                    "instructions": temp_recipe.get("instructions", []),
                    "cuisine": temp_recipe.get("cuisine"),
                }

                candidate_pools[tier].append(meal_candidate)

            best = None
            selected_quality_tier = None

            for tier_name in ("normal", "relaxed", "emergency"):
                pool = candidate_pools.get(tier_name, [])
                if not pool:
                    continue

                pool.sort(
                    key=lambda item: float(item.get("score", 0.0) or 0.0),
                    reverse=True,
                )
                best = pool[0]
                selected_quality_tier = tier_name
                break

            if best is not None:
                components = best.setdefault("components", {})
                components["selected_quality_tier"] = selected_quality_tier
                components["quality_pool_sizes"] = {
                    "normal": len(candidate_pools.get("normal", [])),
                    "relaxed": len(candidate_pools.get("relaxed", [])),
                    "emergency": len(candidate_pools.get("emergency", [])),
                    "blocked": len(blocked_candidates_debug),
                }

            if best is None:
                logger.warning(
                    f"No meal selected for day={day_number}, slot={slot_idx + 1}, meal_type={meal_type}"
                )
                continue

            selected_signatures.add(self._recipe_signature(best["ingredients"]))

            best_main_carb = self._detect_main_carb(best.get("ingredients", []))
            if best_main_carb:
                used_main_carbs.append(best_main_carb)

            meals.append(best)

            recipe_history_key = self._recipe_history_key(best.get("name"))
            if recipe_history_key:
                recent_recipe_names.append(recipe_history_key)
                self._trim_recent_recipe_history(recent_recipe_names)
                try:
                    setattr(user_profile, "recent_recipe_names", list(recent_recipe_names))
                except Exception:
                    pass

            self._add_nutrition_to_totals(day_totals, best["nutrition"])

            if hasattr(user_profile, "add_meal"):
                try:
                    user_profile.add_meal(best["ingredient_names"])
                except Exception as exc:
                    logger.warning(f"Failed to update profile meal history: {exc}")

        day_score = sum(m["score"] for m in meals) / len(meals) if meals else 0.0

        meals = self._check_meal_balance(meals, macro_targets)
        day_warnings = self._day_warnings(day_totals, target_calories, macro_targets)

        return {
            "day": day_number,
            "target_calories": target_calories,
            "macro_targets": macro_targets,
            "meals": meals,
            "day_total": {
                key: round(value, 1)
                for key, value in day_totals.items()
            },
            "day_score": round(day_score, 3),
            "warnings": day_warnings,
        }

    def _check_meal_balance(self, meals: list, macro_targets: dict) -> list:
        if not meals:
            return meals

        total_protein = sum(m["nutrition"].get("protein", 0) for m in meals)
        target_protein = macro_targets.get("protein_g", 0)

        if target_protein > 0 and total_protein < target_protein * 0.85:
            logger.warning(
                f"Protein gap: {total_protein:.1f}g / {target_protein:.1f}g "
                f"({total_protein / target_protein * 100:.0f}%)"
            )
            for meal in meals:
                meal["protein_warning"] = True

        return meals

    def _day_warnings(
        self,
        day_totals: Dict[str, float],
        target_calories: int,
        macro_targets: Dict[str, float],
    ) -> List[str]:
        warnings = []

        calories = day_totals.get("calories", 0.0)
        protein = day_totals.get("protein", 0.0)
        fat = day_totals.get("fat", 0.0)
        carbs = day_totals.get("carbs", 0.0)

        if target_calories > 0:
            if calories < target_calories * 0.9:
                warnings.append("calories_below_target")
            elif calories > target_calories * 1.1:
                warnings.append("calories_above_target")

        protein_target = macro_targets.get("protein_g", 0.0)
        if protein_target > 0 and protein < protein_target * 0.85:
            warnings.append("protein_below_target")

        fat_target = macro_targets.get("fat_g", 0.0)
        if fat_target > 0:
            if fat < fat_target * 0.75:
                warnings.append("fat_below_target")
            elif fat > fat_target * 1.2:
                warnings.append("fat_above_target")

        carbs_target = macro_targets.get("carbs_g", 0.0)
        if carbs_target > 0 and carbs > carbs_target * 1.25:
            warnings.append("carbs_above_target")

        return warnings

    # ==============================
    # LLM REVIEW / EXPLANATION
    # ==============================

    def _llm_review(self, plan: Dict[str, Any], user_profile) -> Dict[str, Any]:
        prompt = f"""
You are a nutrition quality checker.

Check this meal plan for:
- consistency with the user's goal
- allergy/restriction safety
- repetition
- calorie balance
- macro balance

Return STRICT JSON ONLY:
{{
  "safe": true/false,
  "quality_score": number,
  "issues": ["..."],
  "strengths": ["..."],
  "risk_days": [1,2],
  "short_note": "..."
}}

User profile:
{{
  "goal": {repr(getattr(user_profile, "goal", None))},
  "target_calories": {repr(getattr(user_profile, "target_calories", None))},
  "meals_per_day": {repr(getattr(user_profile, "meals_per_day", None))},
  "allergies": {repr(getattr(user_profile, "allergies", []))},
  "preferred_ingredients": {repr(getattr(user_profile, "preferred_ingredients", []))},
  "disliked_ingredients": {repr(getattr(user_profile, "disliked_ingredients", []))},
  "excluded_ingredients": {repr(getattr(user_profile, "excluded_ingredients", []))}
}}

Meal plan:
{plan}
"""
        data = self.llm.generate_json(prompt)
        if not isinstance(data, dict):
            return {
                "safe": False,
                "quality_score": 0,
                "issues": ["LLM review failed"],
                "strengths": [],
                "risk_days": [],
                "short_note": "",
            }
        return data

    def _llm_explain(self, plan: Dict[str, Any], user_profile) -> Dict[str, Any]:
        prompt = f"""
You are a friendly premium meal-planning assistant.

Explain why this meal plan is good for the user.
Do not change the plan.
Do not invent ingredients.
Be concise, helpful, and premium-looking.

Return STRICT JSON ONLY:
{{
  "summary": "...",
  "overall_fit": number,
  "highlights": ["..."],
  "day_explanations": [
    {{
      "day": 1,
      "why_it_works": "...",
      "what_it_optimizes": "...",
      "caution": "..."
    }}
  ]
}}

User profile:
{{
  "goal": {repr(getattr(user_profile, "goal", None))},
  "target_calories": {repr(getattr(user_profile, "target_calories", None))},
  "meals_per_day": {repr(getattr(user_profile, "meals_per_day", None))},
  "allergies": {repr(getattr(user_profile, "allergies", []))},
  "preferred_ingredients": {repr(getattr(user_profile, "preferred_ingredients", []))},
  "disliked_ingredients": {repr(getattr(user_profile, "disliked_ingredients", []))},
  "excluded_ingredients": {repr(getattr(user_profile, "excluded_ingredients", []))}
}}

Meal plan:
{plan}
"""
        data = self.llm.generate_json(prompt)
        if not isinstance(data, dict):
            return {
                "summary": "",
                "overall_fit": 0,
                "highlights": [],
                "day_explanations": [],
            }
        return data
