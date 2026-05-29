# ai/core/debug_plan_quality_report.py
from __future__ import annotations

import argparse
import inspect
import json
import os
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

MODULE_DIR = Path(__file__).resolve().parent
AI_DIR = MODULE_DIR.parent
PROJECT_ROOT = AI_DIR.parent
DATA_DIR = AI_DIR / "data"
REPORTS_DIR = MODULE_DIR / "reports"


# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT PROFILES
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_PROFILES: List[Dict[str, Any]] = [
    {
        "name": "balanced_2000_3",
        "goal": "balanced",
        "target_calories": 2000,
        "calories": 2000,
        "kcal": 2000,
        "meals_per_day": 3,
        "sex": "male",
        "age": 25,
        "height_cm": 178,
        "weight_kg": 75,
        "activity_level": "moderate",
        "excluded": [],
        "allergies": [],
        "disliked": [],
        "preferred": [],
    },
    {
        "name": "weight_loss_1800_3",
        "goal": "weight_loss",
        "target_calories": 1800,
        "calories": 1800,
        "kcal": 1800,
        "meals_per_day": 3,
        "sex": "male",
        "age": 25,
        "height_cm": 178,
        "weight_kg": 80,
        "activity_level": "light",
        "excluded": [],
        "allergies": [],
        "disliked": [],
        "preferred": ["chicken", "turkey", "fish", "vegetables"],
    },
    {
        "name": "muscle_gain_2600_4",
        "goal": "muscle_gain",
        "target_calories": 2600,
        "calories": 2600,
        "kcal": 2600,
        "meals_per_day": 4,
        "sex": "male",
        "age": 25,
        "height_cm": 178,
        "weight_kg": 78,
        "activity_level": "active",
        "excluded": [],
        "allergies": [],
        "disliked": [],
        "preferred": ["beef", "chicken", "rice", "pasta", "eggs"],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# SMALL UTILS
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return float(value)
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_round(value: Any, ndigits: int = 3) -> float:
    return round(safe_float(value), ndigits)


def mean(values: Iterable[float], default: float = 0.0) -> float:
    clean = [safe_float(v) for v in values if v is not None]
    if not clean:
        return default
    return statistics.mean(clean)


def median(values: Iterable[float], default: float = 0.0) -> float:
    clean = [safe_float(v) for v in values if v is not None]
    if not clean:
        return default
    return statistics.median(clean)


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def get_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def print_header(title: str) -> None:
    print()
    print("=" * 96)
    print(title)
    print("=" * 96)


def print_subheader(title: str) -> None:
    print()
    print("-" * 96)
    print(title)


def print_metric(name: str, value: Any) -> None:
    print(f"  {name:36s}: {value}")


def print_counter(title: str, counter: Counter, top_n: int = 15) -> None:
    print_subheader(title)
    if not counter:
        print("  empty")
        return

    for name, count in counter.most_common(top_n):
        print(f"  {str(name):35s} {count}")


def json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE LOADING
# ─────────────────────────────────────────────────────────────────────────────

def load_profiles(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Можно передать кастомные профили через env:

    set AI_FOOD_REPORT_PROFILES_JSON=[{"name":"test","goal":"balanced","target_calories":2000,"meals_per_day":3}]
    """

    raw = os.getenv("AI_FOOD_REPORT_PROFILES_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            profiles = data if isinstance(data, list) else [data]
            profiles = [p for p in profiles if isinstance(p, dict)]
            if profiles:
                return profiles[:limit] if limit else profiles
        except Exception as exc:
            print(f"WARNING: failed to parse AI_FOOD_REPORT_PROFILES_JSON: {exc}")

    profiles = list(DEFAULT_PROFILES)
    return profiles[:limit] if limit else profiles


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT / INIT
# ─────────────────────────────────────────────────────────────────────────────

def import_meal_planner():
    try:
        from ai.core.meal_planner import MealPlanner
    except Exception as exc:
        raise RuntimeError(
            "Cannot import MealPlanner from ai.core.meal_planner. "
            "Run from project root: python -m ai.core.debug_plan_quality_report"
        ) from exc

    return MealPlanner


def import_first(candidates: List[str]):
    last_error: Optional[BaseException] = None

    for dotted in candidates:
        try:
            module_name, class_name = dotted.rsplit(".", 1)
            module = __import__(module_name, fromlist=[class_name])
            return getattr(module, class_name)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Cannot import any of: {candidates}. Last error: {last_error}")


def instantiate_with_supported_kwargs(cls: Any, *positional: Any, **possible_kwargs: Any) -> Any:
    """
    Создаёт объект, передавая только те keyword-аргументы, которые реально есть
    в __init__. Это защищает от разных версий твоих классов.
    """

    try:
        sig = inspect.signature(cls)
        params = sig.parameters
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

        if has_kwargs:
            kwargs = possible_kwargs
        else:
            kwargs = {k: v for k, v in possible_kwargs.items() if k in params}

        return cls(*positional, **kwargs)
    except TypeError:
        # fallback: иногда класс лучше принимает только позиционные аргументы
        if positional:
            return cls(*positional)
        return cls()


class ReportUserProfile:
    """
    Объектный профиль для MealPlanner.

    Нужен потому что многие версии MealPlanner читают профиль через getattr(...),
    а не через dict.get(...).
    """

    def __init__(self, data: Dict[str, Any]):
        self.raw = dict(data)

        self.name = data.get("name", data.get("goal", "profile"))
        self.goal = data.get("goal", "balanced")

        self.meals_per_day = safe_int(data.get("meals_per_day", 3), 3)
        self.target_calories = safe_int(
            data.get("target_calories", data.get("calories", data.get("kcal", 2000))),
            2000,
        )
        self.calories = self.target_calories
        self.kcal = self.target_calories

        self.age = safe_int(data.get("age", 25), 25)
        self.sex = data.get("sex", "male")
        self.height_cm = safe_float(data.get("height_cm", 178), 178)
        self.weight_kg = safe_float(data.get("weight_kg", 75), 75)
        self.activity_level = data.get("activity_level", "moderate")

        self.protein_target_g = data.get("protein_target_g", None)
        self.fat_target_g = data.get("fat_target_g", None)
        self.carb_limit_g = data.get("carb_limit_g", None)

        self.allergies = list(data.get("allergies", []))
        self.preferred_ingredients = list(
            data.get("preferred_ingredients", data.get("preferred", []))
        )
        self.disliked_ingredients = list(
            data.get("disliked_ingredients", data.get("disliked", []))
        )
        self.excluded_ingredients = list(
            data.get("excluded_ingredients", data.get("excluded", []))
        )

        # aliases для разных версий кода
        self.preferred = self.preferred_ingredients
        self.disliked = self.disliked_ingredients
        self.excluded = self.excluded_ingredients

        self.recent_meals: List[Dict[str, Any]] = list(data.get("recent_meals", []))

    def add_meal(self, ingredients: Iterable[Any]) -> None:
        normalized = []

        for ing in ingredients:
            if isinstance(ing, dict):
                name = ing.get("name") or ing.get("canonical_name") or ""
            else:
                name = str(ing or "")

            name = str(name).lower().strip().replace(" ", "_")
            if name:
                normalized.append(name)

        self.recent_meals.append({"ingredients": normalized})

        if len(self.recent_meals) > 30:
            self.recent_meals.pop(0)

    def get_recent_ingredients(self) -> set:
        result = set()

        for meal in self.recent_meals:
            if isinstance(meal, dict):
                result.update(meal.get("ingredients", []))

        return result

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.raw)
        data.update(
            {
                "name": self.name,
                "goal": self.goal,
                "target_calories": self.target_calories,
                "meals_per_day": self.meals_per_day,
                "age": self.age,
                "sex": self.sex,
                "height_cm": self.height_cm,
                "weight_kg": self.weight_kg,
                "activity_level": self.activity_level,
                "allergies": self.allergies,
                "preferred_ingredients": self.preferred_ingredients,
                "disliked_ingredients": self.disliked_ingredients,
                "excluded_ingredients": self.excluded_ingredients,
                "recent_meals": self.recent_meals,
            }
        )
        return data


def make_user_profile(profile: Dict[str, Any]) -> ReportUserProfile:
    return ReportUserProfile(profile)


def init_recipe_search(RecipeSearch: Any):
    recipes_path = AI_DIR / "recipes" / "recipes.json"
    index_path = AI_DIR / "recipes" / "recipe_index.faiss"
    embeddings_path = AI_DIR / "recipes" / "recipe_embeddings.npy"

    recipe_search_attempts = [
        {},
        {
            "recipes_path": recipes_path,
            "index_path": index_path,
            "embeddings_path": embeddings_path,
        },
        {
            "recipes_file": recipes_path,
            "index_file": index_path,
            "embeddings_file": embeddings_path,
        },
        {
            "recipes_json": recipes_path,
            "faiss_index": index_path,
            "embeddings": embeddings_path,
        },
    ]

    recipe_search = None
    last_recipe_search_error = None

    for kwargs in recipe_search_attempts:
        try:
            recipe_search = RecipeSearch(**kwargs)
            print(f"OK RecipeSearch init with kwargs={list(kwargs.keys())}")
            break
        except Exception as exc:
            last_recipe_search_error = exc

    if recipe_search is None:
        raise RuntimeError(
            f"RecipeSearch не инициализируется: "
            f"{type(last_recipe_search_error).__name__}: {last_recipe_search_error}"
        )

    return recipe_search


def optional_instance(candidates: List[str]):
    try:
        cls = import_first(candidates)
        return cls()
    except Exception as exc:
        print(
            f"WARNING: optional dependency not created: "
            f"{candidates[0]} -> {type(exc).__name__}: {exc}"
        )
        return None


def init_meal_planner():
    """
    Совместимая инициализация под твою текущую prod-структуру.

    Твой MealPlanner требует:
      MealPlanner(recipe_search, nutrition_engine, ...)
    """

    MealPlanner = import_meal_planner()

    NutritionEngine = import_first(
        [
            "ai.core.nutrition_engine.NutritionEngine",
            "ai.llm.nutrition_engine.NutritionEngine",
        ]
    )

    RecipeSearch = import_first(
        [
            "ai.recipes.recipe_search.RecipeSearch",
        ]
    )

    PortionOptimizer = import_first(
        [
            "ai.core.decision.portion_optimizer.PortionOptimizer",
        ]
    )

    engine = NutritionEngine()
    optimizer = instantiate_with_supported_kwargs(
        PortionOptimizer,
        engine,
        nutrition_engine=engine,
    )
    recipe_search = init_recipe_search(RecipeSearch)

    safety_checker = optional_instance(["ai.core.decision.safety_checker.SafetyChecker"])
    preference_scorer = optional_instance(["ai.core.decision.preference_scorer.PreferenceScorer"])
    diversity_engine = optional_instance(["ai.core.decision.diversity_engine.DiversityEngine"])
    substitution_engine = optional_instance(["ai.core.decision.substitution_engine.SubstitutionEngine"])

    try:
        planner = instantiate_with_supported_kwargs(
            MealPlanner,
            recipe_search,
            engine,
            recipe_search=recipe_search,
            nutrition_engine=engine,
            safety_checker=safety_checker,
            preference_scorer=preference_scorer,
            diversity_engine=diversity_engine,
            substitution_engine=substitution_engine,
            portion_optimizer=optimizer,
            llm=None,
        )
    except TypeError:
        # самый простой fallback для старой сигнатуры
        planner = MealPlanner(recipe_search, engine)

        if hasattr(planner, "portion_optimizer"):
            setattr(planner, "portion_optimizer", optimizer)

    print("OK MealPlanner initialized")
    return planner


# ─────────────────────────────────────────────────────────────────────────────
# BUILD PLAN COMPATIBILITY
# ─────────────────────────────────────────────────────────────────────────────

def build_plan_compatible(
    planner: Any,
    profile: Dict[str, Any],
    days: int,
    candidate_limit: int,
) -> Dict[str, Any]:
    """
    Поддерживает несколько возможных сигнатур build_plan:
    1. build_plan(profile=..., days=..., candidate_limit=...)
    2. build_plan(user_profile=..., days=..., candidate_limit=...)
    3. build_plan(goal=..., target_calories=..., meals_per_day=..., days=..., ...)
    4. build_plan(profile, days=...)
    """

    method = planner.build_plan

    goal = str(profile.get("goal", "balanced"))
    target_calories = safe_float(
        profile.get("target_calories", profile.get("calories", profile.get("kcal", 2000))),
        2000,
    )
    meals_per_day = safe_int(profile.get("meals_per_day", 3), 3)
    excluded = profile.get("excluded", profile.get("excluded_ingredients", []))
    user_profile = make_user_profile(profile)

    attempts: List[Tuple[str, Dict[str, Any], Tuple[Any, ...]]] = []

    try:
        sig = inspect.signature(method)
        params = sig.parameters
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

        kwargs: Dict[str, Any] = {}

        def add_if_supported(name: str, value: Any) -> None:
            if has_kwargs or name in params:
                kwargs[name] = value

        if "profile" in params or has_kwargs:
            add_if_supported("profile", user_profile)
        elif "user_profile" in params:
            add_if_supported("user_profile", user_profile)
        elif "preferences" in params:
            add_if_supported("preferences", profile)

        add_if_supported("goal", goal)
        add_if_supported("target_calories", target_calories)
        add_if_supported("calories", target_calories)
        add_if_supported("kcal", target_calories)
        add_if_supported("days", days)
        add_if_supported("num_days", days)
        add_if_supported("meals_per_day", meals_per_day)
        add_if_supported("excluded", excluded)
        add_if_supported("excluded_ingredients", excluded)
        add_if_supported("candidate_limit", candidate_limit)
        add_if_supported("limit", candidate_limit)

        if kwargs:
            attempts.append(("signature_kwargs", kwargs, ()))
    except Exception:
        pass

    attempts.extend(
        [
            (
                "profile_kwargs",
                {
                    "profile": user_profile,
                    "days": days,
                    "candidate_limit": candidate_limit,
                },
                (),
            ),
            (
                "user_profile_kwargs",
                {
                    "user_profile": user_profile,
                    "days": days,
                    "candidate_limit": candidate_limit,
                },
                (),
            ),
            (
                "explicit_kwargs",
                {
                    "goal": goal,
                    "target_calories": target_calories,
                    "meals_per_day": meals_per_day,
                    "days": days,
                    "excluded": excluded,
                    "candidate_limit": candidate_limit,
                },
                (),
            ),
            (
                "explicit_without_candidate_limit",
                {
                    "goal": goal,
                    "target_calories": target_calories,
                    "meals_per_day": meals_per_day,
                    "days": days,
                    "excluded": excluded,
                },
                (),
            ),
            (
                "profile_positional",
                {
                    "days": days,
                    "candidate_limit": candidate_limit,
                },
                (user_profile,),
            ),
            (
                "profile_positional_no_candidate_limit",
                {
                    "days": days,
                },
                (user_profile,),
            ),
            (
                "minimal",
                {
                    "days": days,
                },
                (),
            ),
        ]
    )

    last_error: Optional[BaseException] = None

    for name, kwargs, args in attempts:
        try:
            result = method(*args, **kwargs)

            if isinstance(result, dict):
                result["_debug_call_variant"] = name
                return result

            return {
                "_debug_call_variant": name,
                "raw_result": result,
            }
        except TypeError as exc:
            last_error = exc
            continue
        except Exception:
            raise

    raise RuntimeError(f"Cannot call MealPlanner.build_plan. Last TypeError: {last_error}")


# ─────────────────────────────────────────────────────────────────────────────
# PLAN NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def extract_plan_days(plan_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("plan", "days", "meal_plan"):
        value = plan_result.get(key)
        if isinstance(value, list):
            return [d for d in value if isinstance(d, dict)]

    nested = plan_result.get("result")
    if isinstance(nested, dict):
        return extract_plan_days(nested)

    raw = plan_result.get("raw_result")
    if isinstance(raw, list):
        return [d for d in raw if isinstance(d, dict)]

    return []


def extract_day_meals(day: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("meals", "slots", "items"):
        value = day.get(key)
        if isinstance(value, list):
            return [m for m in value if isinstance(m, dict)]
    return []


def get_day_total(day: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("day_total", "total", "nutrition", "daily_total"):
        value = day.get(key)
        if isinstance(value, dict):
            return value
    return {}


def get_macro_targets(
    plan_result: Dict[str, Any],
    day: Dict[str, Any],
    profile: Dict[str, Any],
) -> Dict[str, float]:
    day_targets = get_dict(day.get("macro_targets"))
    root_targets = get_dict(plan_result.get("macro_targets"))

    target_calories = safe_float(
        day.get(
            "target_calories",
            plan_result.get(
                "target_calories",
                profile.get("target_calories", profile.get("calories", profile.get("kcal", 0))),
            ),
        )
    )

    return {
        "calories": target_calories,
        "protein": safe_float(
            day_targets.get("protein_g", day_targets.get("protein", root_targets.get("protein_g", root_targets.get("protein", 0))))
        ),
        "fat": safe_float(
            day_targets.get("fat_g", day_targets.get("fat", root_targets.get("fat_g", root_targets.get("fat", 0))))
        ),
        "carbs": safe_float(
            day_targets.get("carbs_g", day_targets.get("carbs", root_targets.get("carbs_g", root_targets.get("carbs", 0))))
        ),
    }


def normalize_tier(value: Any) -> str:
    tier = str(value or "").strip().lower()
    if not tier:
        return "unknown"
    if tier in {"normal", "relaxed", "emergency", "blocked"}:
        return tier
    return tier


def extract_components(meal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Собирает debug-компоненты из разных возможных мест.

    Разные версии MealPlanner могут класть данные в:
    - components
    - rerank_components
    - quality_components
    - selection_components

    Для отчёта нам нужен единый словарь, иначе поля вроде
    selection_tier_reason / low_score_policy_applied могут теряться.
    """
    result: Dict[str, Any] = {}

    for key in (
        "components",
        "rerank_components",
        "quality_components",
        "selection_components",
    ):
        value = meal.get(key)
        if isinstance(value, dict):
            result.update(value)

    return result


def extract_tier(meal: Dict[str, Any]) -> str:
    components = extract_components(meal)

    for key in (
        "selected_quality_tier",
        "selection_quality_tier",
        "selection_tier",
        "quality_tier",
        "tier",
    ):
        if key in components:
            return normalize_tier(components.get(key))

    for key in (
        "selected_quality_tier",
        "selection_quality_tier",
        "selection_tier",
        "quality_tier",
        "tier",
    ):
        if key in meal:
            return normalize_tier(meal.get(key))

    return "unknown"


def extract_main_carb(meal: Dict[str, Any]) -> Optional[str]:
    components = extract_components(meal)
    main_carb = components.get("main_carb")

    if main_carb:
        return str(main_carb)

    for ing in get_list(meal.get("ingredients")):
        if not isinstance(ing, dict):
            continue

        role = str(ing.get("role", "")).lower()
        name = ing.get("name") or ing.get("canonical_name")

        if role in {"carbs", "carb", "main_carb", "starch"} and name:
            return str(name)

    return None


def extract_main_proteins(meal: Dict[str, Any]) -> List[str]:
    result: List[str] = []

    for ing in get_list(meal.get("ingredients")):
        if not isinstance(ing, dict):
            continue

        role = str(ing.get("role", "")).lower()
        name = ing.get("name") or ing.get("canonical_name")

        if not name:
            continue

        if role in {"protein", "main_protein"}:
            result.append(str(name))

    return result


def extract_nutrition(meal: Dict[str, Any]) -> Dict[str, Any]:
    value = meal.get("nutrition")
    return value if isinstance(value, dict) else {}


def extract_portion(meal: Dict[str, Any]) -> Dict[str, Any]:
    value = meal.get("portion")
    return value if isinstance(value, dict) else {}


def extract_quality_pool_sizes(meal: Dict[str, Any]) -> Dict[str, int]:
    components = extract_components(meal)
    value = components.get("quality_pool_sizes")

    if isinstance(value, dict):
        return {str(k): safe_int(v) for k, v in value.items()}

    value = meal.get("quality_pool_sizes")
    if isinstance(value, dict):
        return {str(k): safe_int(v) for k, v in value.items()}

    return {}


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def macro_deviation(actual: float, target: float) -> Dict[str, float]:
    if target <= 0:
        return {
            "actual": round(actual, 3),
            "target": round(target, 3),
            "ratio": 0.0,
            "abs_pct_error": 0.0,
        }

    ratio = actual / target
    return {
        "actual": round(actual, 3),
        "target": round(target, 3),
        "ratio": round(ratio, 4),
        "abs_pct_error": round(abs(ratio - 1.0), 4),
    }


def analyze_plan(
    profile: Dict[str, Any],
    plan_result: Dict[str, Any],
    elapsed_s: float,
) -> Dict[str, Any]:
    days = extract_plan_days(plan_result)
    expected_days = safe_int(profile.get("days", len(days)), len(days))
    meals_per_day = safe_int(
        plan_result.get("meals_per_day", profile.get("meals_per_day", 3)),
        3,
    )
    expected_meals = expected_days * meals_per_day

    recipe_counter: Counter = Counter()
    meal_type_counter: Counter = Counter()
    tier_counter: Counter = Counter()
    main_carb_counter: Counter = Counter()
    main_protein_counter: Counter = Counter()
    cuisine_counter: Counter = Counter()
    ingredient_counter: Counter = Counter()
    quality_pool_totals: Counter = Counter()

    day_scores: List[float] = []
    meal_scores: List[float] = []
    portion_scores: List[float] = []
    slot_macro_fits: List[float] = []
    retrieval_scores: List[float] = []
    diversity_scores: List[float] = []
    preference_scores: List[float] = []
    meal_type_fits: List[float] = []
    satiety_scores: List[float] = []
    eaten_weights: List[float] = []
    energy_densities: List[float] = []

    day_reports: List[Dict[str, Any]] = []
    meal_reports: List[Dict[str, Any]] = []
    problems: List[Dict[str, Any]] = []

    daily_abs_errors = {
        "calories": [],
        "protein": [],
        "fat": [],
        "carbs": [],
    }

    generated_meals = 0

    for day_index, day in enumerate(days, start=1):
        meals = extract_day_meals(day)
        generated_meals += len(meals)

        day_score = safe_float(day.get("day_score", day.get("score", 0.0)))
        if day_score:
            day_scores.append(day_score)

        day_total = get_day_total(day)
        targets = get_macro_targets(plan_result, day, profile)

        macro_report: Dict[str, Dict[str, float]] = {}
        for key in ("calories", "protein", "fat", "carbs"):
            actual = safe_float(day_total.get(key, 0.0))
            target = safe_float(targets.get(key, 0.0))
            dev = macro_deviation(actual, target)
            macro_report[key] = dev

            if target > 0:
                daily_abs_errors[key].append(dev["abs_pct_error"])

        day_report = {
            "day": day.get("day", day_index),
            "day_score": safe_round(day_score, 3),
            "meals_count": len(meals),
            "target_calories": safe_round(targets.get("calories", 0.0), 1),
            "day_total": {
                "calories": safe_round(day_total.get("calories"), 1),
                "protein": safe_round(day_total.get("protein"), 1),
                "fat": safe_round(day_total.get("fat"), 1),
                "carbs": safe_round(day_total.get("carbs"), 1),
                "fiber": safe_round(day_total.get("fiber"), 1),
                "sugar": safe_round(day_total.get("sugar"), 1),
                "sodium_mg": safe_round(day_total.get("sodium_mg"), 1),
                "saturated_fat": safe_round(day_total.get("saturated_fat"), 1),
                "eaten_weight_g": safe_round(day_total.get("eaten_weight_g"), 1),
            },
            "macro_deviation": macro_report,
            "meals": [],
        }

        if len(meals) != meals_per_day:
            problems.append(
                {
                    "severity": "critical",
                    "type": "wrong_meals_per_day",
                    "day": day_index,
                    "message": f"Expected {meals_per_day} meals, got {len(meals)}",
                }
            )

        for slot_index, meal in enumerate(meals, start=1):
            name = str(meal.get("name", "<unnamed>"))
            meal_type = str(meal.get("meal_type", f"slot_{slot_index}"))
            cuisine = str(meal.get("cuisine", "unknown") or "unknown")

            components = extract_components(meal)
            nutrition = extract_nutrition(meal)
            portion = extract_portion(meal)

            tier = extract_tier(meal)
            main_carb = extract_main_carb(meal)
            main_proteins = extract_main_proteins(meal)

            score = safe_float(meal.get("score", meal.get("rerank_score", 0.0)))
            portion_score = safe_float(portion.get("score", components.get("portion_score", 0.0)))
            slot_macro_fit = safe_float(components.get("slot_macro_fit", 0.0))
            retrieval = safe_float(components.get("retrieval", components.get("embedding_score", 0.0)))
            diversity = safe_float(components.get("diversity", 0.0))
            preference = safe_float(components.get("preference", 0.0))
            meal_type_fit = safe_float(components.get("meal_type_fit", 0.0))
            satiety = safe_float(nutrition.get("satiety_score", components.get("satiety_score", 0.0)))
            eaten_weight = safe_float(nutrition.get("eaten_weight_g", portion.get("eaten_weight_g", 0.0)))
            energy_density = safe_float(nutrition.get("energy_density_kcal_per_g", 0.0))

            recipe_counter[name] += 1
            meal_type_counter[meal_type] += 1
            tier_counter[tier] += 1
            cuisine_counter[cuisine] += 1

            if main_carb:
                main_carb_counter[main_carb] += 1

            for p in main_proteins:
                main_protein_counter[p] += 1

            for ing in get_list(meal.get("ingredients")):
                if isinstance(ing, dict):
                    ing_name = ing.get("name") or ing.get("canonical_name")
                    if ing_name:
                        ingredient_counter[str(ing_name)] += 1
                elif isinstance(ing, str):
                    ingredient_counter[ing] += 1

            for k, v in extract_quality_pool_sizes(meal).items():
                quality_pool_totals[k] += v

            meal_scores.append(score)
            if portion_score:
                portion_scores.append(portion_score)
            if slot_macro_fit:
                slot_macro_fits.append(slot_macro_fit)
            if retrieval:
                retrieval_scores.append(retrieval)
            if diversity:
                diversity_scores.append(diversity)
            if preference:
                preference_scores.append(preference)
            if meal_type_fit:
                meal_type_fits.append(meal_type_fit)
            if satiety:
                satiety_scores.append(satiety)
            if eaten_weight:
                eaten_weights.append(eaten_weight)
            if energy_density:
                energy_densities.append(energy_density)

            selection_tier_reason = (
                meal.get("selection_tier_reason")
                or meal.get("selection_quality_reason")
                or meal.get("tier_reason")
                or meal.get("quality_reason")
                or components.get("selection_tier_reason")
                or components.get("selection_quality_reason")
                or components.get("tier_reason")
                or components.get("quality_reason")
                or ""
            )

            score_before_low_score_ceiling = (
                meal.get("score_before_low_score_ceiling")
                or meal.get("score_before_ceiling")
                or components.get("score_before_low_score_ceiling")
                or components.get("score_before_ceiling")
            )

            low_score_policy_applied = bool(
                meal.get(
                    "low_score_policy_applied",
                    components.get("low_score_policy_applied", False),
                )
            )

            low_score_policy_reason = (
                meal.get("low_score_policy_reason")
                or meal.get("low_score_reason")
                or components.get("low_score_policy_reason")
                or components.get("low_score_reason")
                or ""
            )

            low_score_policy_score_ceiling = (
                meal.get("low_score_policy_score_ceiling")
                or components.get("low_score_policy_score_ceiling")
            )

            low_score_rescue_applied = bool(
                meal.get(
                    "low_score_rescue_applied",
                    components.get("low_score_rescue_applied", False),
                )
            )

            low_score_before_rescue = (
                meal.get("low_score_before_rescue")
                or components.get("low_score_before_rescue")
            )

            low_score_after_rescue = (
                meal.get("low_score_after_rescue")
                or components.get("low_score_after_rescue")
            )

            low_score_rescue_boost = (
                meal.get("low_score_rescue_boost")
                or components.get("low_score_rescue_boost")
            )

            meal_report = {
                "day": day_index,
                "slot": slot_index,
                "meal_type": meal_type,
                "name": name,
                "tier": tier,
                "selection_tier": tier,
                "score": safe_round(score, 4),
                "portion_score": safe_round(portion_score, 4),
                "slot_macro_fit": safe_round(slot_macro_fit, 4),
                "retrieval": safe_round(retrieval, 4),
                "diversity": safe_round(diversity, 4),
                "preference": safe_round(preference, 4),
                "meal_type_fit": safe_round(meal_type_fit, 4),
                "satiety_score": safe_round(satiety, 3),
                "main_carb": main_carb,
                "main_proteins": main_proteins,
                "calories": safe_round(nutrition.get("calories"), 1),
                "protein": safe_round(nutrition.get("protein"), 1),
                "fat": safe_round(nutrition.get("fat"), 1),
                "carbs": safe_round(nutrition.get("carbs"), 1),
                "eaten_weight_g": safe_round(eaten_weight, 1),
                "energy_density_kcal_per_g": safe_round(energy_density, 3),
                "quality_pool_sizes": extract_quality_pool_sizes(meal),
                "issues": get_list(meal.get("issues")),
                "warnings": get_list(meal.get("warnings")),

                "selection_tier_reason": selection_tier_reason,
                "selection_quality_reason": selection_tier_reason,

                "score_before_low_score_ceiling": score_before_low_score_ceiling,
                "low_score_policy_applied": low_score_policy_applied,
                "low_score_policy_reason": low_score_policy_reason,
                "low_score_policy_score_ceiling": low_score_policy_score_ceiling,

                "low_score_rescue_applied": low_score_rescue_applied,
                "low_score_before_rescue": low_score_before_rescue,
                "low_score_after_rescue": low_score_after_rescue,
                "low_score_rescue_boost": low_score_rescue_boost,

                "components": components,
            }

            day_report["meals"].append(meal_report)
            meal_reports.append(meal_report)

            # ── Problem detection

            if tier == "emergency":
                problems.append(
                    {
                        "severity": "critical",
                        "type": "emergency_selection",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "message": "Meal selected from emergency tier",
                    }
                )
            elif tier == "relaxed":
                problems.append(
                    {
                        "severity": "warning",
                        "type": "relaxed_selection",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "message": "Meal selected from relaxed tier",
                    }
                )

            if score < 0.42:
                problems.append(
                    {
                        "severity": "warning",
                        "type": "low_meal_score",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "score": safe_round(score, 4),
                    }
                )

            if portion_score and portion_score < 0.55:
                problems.append(
                    {
                        "severity": "warning",
                        "type": "low_portion_score",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "portion_score": safe_round(portion_score, 4),
                    }
                )

            if slot_macro_fit and slot_macro_fit < 0.55:
                problems.append(
                    {
                        "severity": "warning",
                        "type": "low_slot_macro_fit",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "slot_macro_fit": safe_round(slot_macro_fit, 4),
                    }
                )

            if eaten_weight and eaten_weight < 160:
                problems.append(
                    {
                        "severity": "warning",
                        "type": "too_small_eaten_weight",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "eaten_weight_g": safe_round(eaten_weight, 1),
                    }
                )

            if eaten_weight and eaten_weight > 1100:
                problems.append(
                    {
                        "severity": "warning",
                        "type": "too_large_eaten_weight",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "eaten_weight_g": safe_round(eaten_weight, 1),
                    }
                )

            if energy_density and energy_density > 3.2:
                problems.append(
                    {
                        "severity": "warning",
                        "type": "high_energy_density",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "energy_density_kcal_per_g": safe_round(energy_density, 3),
                    }
                )

            if safe_int(components.get("meal_type_negative_hits", 0)) > 0:
                problems.append(
                    {
                        "severity": "info",
                        "type": "meal_type_negative_hit",
                        "day": day_index,
                        "slot": slot_index,
                        "meal": name,
                        "negative_hits": safe_int(components.get("meal_type_negative_hits")),
                    }
                )

        day_reports.append(day_report)

    empty_slots = max(0, expected_meals - generated_meals)

    if empty_slots > 0:
        problems.append(
            {
                "severity": "critical",
                "type": "empty_slots",
                "message": f"Generated {generated_meals}/{expected_meals} meals",
                "empty_slots": empty_slots,
            }
        )

    # Repetition analysis after all meals
    for recipe, count in recipe_counter.items():
        if count >= 3:
            problems.append(
                {
                    "severity": "warning",
                    "type": "recipe_repeated_too_often",
                    "recipe": recipe,
                    "count": count,
                }
            )

    for carb, count in main_carb_counter.items():
        if generated_meals > 0 and count / generated_meals >= 0.35:
            problems.append(
                {
                    "severity": "warning",
                    "type": "main_carb_dominance",
                    "main_carb": carb,
                    "count": count,
                    "ratio": round(count / generated_meals, 4),
                }
            )

    summary = {
        "profile": profile.get("name", profile.get("goal", "profile")),
        "goal": profile.get("goal"),
        "target_calories": safe_float(profile.get("target_calories", profile.get("calories", profile.get("kcal", 0)))),
        "meals_per_day": meals_per_day,
        "elapsed_s": round(elapsed_s, 3),
        "expected_days": expected_days,
        "generated_days": len(days),
        "expected_meals": expected_meals,
        "generated_meals": generated_meals,
        "empty_slots": empty_slots,
        "avg_day_score": round(mean(day_scores), 4),
        "min_day_score": round(min(day_scores), 4) if day_scores else 0.0,
        "avg_meal_score": round(mean(meal_scores), 4),
        "min_meal_score": round(min(meal_scores), 4) if meal_scores else 0.0,
        "avg_portion_score": round(mean(portion_scores), 4),
        "min_portion_score": round(min(portion_scores), 4) if portion_scores else 0.0,
        "avg_slot_macro_fit": round(mean(slot_macro_fits), 4),
        "min_slot_macro_fit": round(min(slot_macro_fits), 4) if slot_macro_fits else 0.0,
        "avg_retrieval": round(mean(retrieval_scores), 4),
        "avg_diversity": round(mean(diversity_scores), 4),
        "avg_preference": round(mean(preference_scores), 4),
        "avg_meal_type_fit": round(mean(meal_type_fits), 4),
        "avg_satiety_score": round(mean(satiety_scores), 4),
        "avg_eaten_weight_g": round(mean(eaten_weights), 1),
        "median_eaten_weight_g": round(median(eaten_weights), 1),
        "avg_energy_density_kcal_per_g": round(mean(energy_densities), 3),
        "daily_macro_abs_error_avg": {
            "calories": round(mean(daily_abs_errors["calories"]), 4),
            "protein": round(mean(daily_abs_errors["protein"]), 4),
            "fat": round(mean(daily_abs_errors["fat"]), 4),
            "carbs": round(mean(daily_abs_errors["carbs"]), 4),
        },
        "tier_counts": dict(tier_counter),
        "quality_pool_totals": dict(quality_pool_totals),
        "recipe_counts": dict(recipe_counter),
        "main_carb_counts": dict(main_carb_counter),
        "main_protein_counts": dict(main_protein_counter),
        "meal_type_counts": dict(meal_type_counter),
        "cuisine_counts": dict(cuisine_counter),
        "top_ingredients": dict(ingredient_counter.most_common(50)),
        "problems_count": len(problems),
        "critical_count": sum(1 for p in problems if p.get("severity") == "critical"),
        "warning_count": sum(1 for p in problems if p.get("severity") == "warning"),
    }

    recommendations = build_recommendations(summary, problems)

    return {
        "summary": summary,
        "days": day_reports,
        "meals": meal_reports,
        "problems": problems,
        "recommendations": recommendations,
        "raw_call_variant": plan_result.get("_debug_call_variant"),
    }


def build_recommendations(summary: Dict[str, Any], problems: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []

    empty_slots = safe_int(summary.get("empty_slots"))
    if empty_slots:
        recommendations.append(
            "Есть пустые слоты. Проверь candidate_limit, staged fallback и hard-block правила."
        )

    tier_counts = get_dict(summary.get("tier_counts"))
    emergency_count = safe_int(tier_counts.get("emergency"))
    relaxed_count = safe_int(tier_counts.get("relaxed"))

    if emergency_count:
        recommendations.append(
            "Есть emergency selections. Нужно ослабить слишком жёсткие фильтры или расширить candidate pool."
        )

    if relaxed_count:
        recommendations.append(
            "Есть relaxed selections. Это допустимо, но стоит посмотреть, какие именно правила не дают normal-кандидатов."
        )

    macro_errors = get_dict(summary.get("daily_macro_abs_error_avg"))
    if safe_float(macro_errors.get("calories")) > 0.10:
        recommendations.append(
            "Среднее отклонение калорий выше 10%. Усилить calorie_fit/portion optimizer или day calorie pressure."
        )

    if safe_float(macro_errors.get("protein")) > 0.20:
        recommendations.append(
            "Среднее отклонение белка выше 20%. Усилить protein floor / protein priority по слотам."
        )

    if safe_float(macro_errors.get("fat")) > 0.22:
        recommendations.append(
            "Среднее отклонение жиров выше 22%. Усилить fat_over_penalty и ограничить жирные компоненты."
        )

    if safe_float(macro_errors.get("carbs")) > 0.22:
        recommendations.append(
            "Среднее отклонение углеводов выше 22%. Проверить main_carb scaling и slot carb targets."
        )

    generated_meals = max(1, safe_int(summary.get("generated_meals")))
    main_carb_counts = get_dict(summary.get("main_carb_counts"))
    if main_carb_counts:
        top_carb, top_count = max(main_carb_counts.items(), key=lambda kv: safe_int(kv[1]))
        if safe_int(top_count) / generated_meals >= 0.35:
            recommendations.append(
                f"Main carb '{top_carb}' занимает >=35% слотов. Усилить main_carb_repeat_penalty / diversity."
            )

    recipe_counts = get_dict(summary.get("recipe_counts"))
    repeated = [(k, v) for k, v in recipe_counts.items() if safe_int(v) >= 3]
    if repeated:
        recommendations.append(
            "Есть рецепты, повторяющиеся 3+ раза. Усилить recipe cooldown и history penalty."
        )

    low_portion = [p for p in problems if p.get("type") == "low_portion_score"]
    if low_portion:
        recommendations.append(
            "Есть low_portion_score. Проверь portion_rules min/max/typical_g для проблемных ингредиентов."
        )

    if not recommendations:
        recommendations.append(
            "Критичных проблем не найдено. Следующий этап — ручная оценка качества выбранных блюд и UX-формат выдачи."
        )

    return recommendations


# ─────────────────────────────────────────────────────────────────────────────
# PRINTING
# ─────────────────────────────────────────────────────────────────────────────

def print_profile_report(report: Dict[str, Any], top_n: int = 15) -> None:
    summary = report["summary"]
    problems = report["problems"]
    recommendations = report["recommendations"]

    print_header(f"PROFILE REPORT: {summary['profile']}")

    print_subheader("SUMMARY")
    print_metric("goal", summary.get("goal"))
    print_metric("target_calories", summary.get("target_calories"))
    print_metric("elapsed_s", summary.get("elapsed_s"))
    print_metric("generated_days", f"{summary.get('generated_days')}/{summary.get('expected_days')}")
    print_metric("generated_meals", f"{summary.get('generated_meals')}/{summary.get('expected_meals')}")
    print_metric("empty_slots", summary.get("empty_slots"))
    print_metric("avg_day_score", summary.get("avg_day_score"))
    print_metric("min_day_score", summary.get("min_day_score"))
    print_metric("avg_meal_score", summary.get("avg_meal_score"))
    print_metric("min_meal_score", summary.get("min_meal_score"))
    print_metric("avg_portion_score", summary.get("avg_portion_score"))
    print_metric("min_portion_score", summary.get("min_portion_score"))
    print_metric("avg_slot_macro_fit", summary.get("avg_slot_macro_fit"))
    print_metric("min_slot_macro_fit", summary.get("min_slot_macro_fit"))
    print_metric("avg_satiety_score", summary.get("avg_satiety_score"))
    print_metric("avg_eaten_weight_g", summary.get("avg_eaten_weight_g"))
    print_metric("avg_energy_density_kcal_per_g", summary.get("avg_energy_density_kcal_per_g"))

    macro_errors = get_dict(summary.get("daily_macro_abs_error_avg"))
    print_subheader("AVG DAILY MACRO ABS ERROR")
    for key in ("calories", "protein", "fat", "carbs"):
        print_metric(key, pct(safe_float(macro_errors.get(key))))

    print_counter("SELECTION TIERS", Counter(summary.get("tier_counts", {})), top_n=10)
    print_counter("MAIN CARBS", Counter(summary.get("main_carb_counts", {})), top_n=top_n)
    print_counter("MAIN PROTEINS", Counter(summary.get("main_protein_counts", {})), top_n=top_n)
    print_counter("RECIPES", Counter(summary.get("recipe_counts", {})), top_n=top_n)
    print_counter("MEAL TYPES", Counter(summary.get("meal_type_counts", {})), top_n=10)
    print_counter("CUISINES", Counter(summary.get("cuisine_counts", {})), top_n=10)

    print_subheader("DAY TABLE")
    for day in report["days"]:
        dev = day["macro_deviation"]
        total = day["day_total"]

        print(
            f"day={str(day['day']).rjust(2)} "
            f"score={day['day_score']:.3f} "
            f"meals={day['meals_count']} "
            f"kcal={total['calories']:.1f}/{day['target_calories']:.1f} "
            f"kcal_err={pct(dev['calories']['abs_pct_error'])} "
            f"P={total['protein']:.1f} err={pct(dev['protein']['abs_pct_error'])} "
            f"F={total['fat']:.1f} err={pct(dev['fat']['abs_pct_error'])} "
            f"C={total['carbs']:.1f} err={pct(dev['carbs']['abs_pct_error'])} "
            f"weight={total['eaten_weight_g']:.1f}g"
        )

    print_subheader("LOWEST MEALS BY SCORE")

    meals_sorted = sorted(
        report["meals"],
        key=lambda m: safe_float(m.get("score")),
    )

    for m in meals_sorted[:top_n]:
        components = {}

        if isinstance(m.get("components"), dict):
            components.update(m.get("components") or {})

        if isinstance(m.get("rerank_components"), dict):
            components.update(m.get("rerank_components") or {})

        if isinstance(m.get("quality_components"), dict):
            components.update(m.get("quality_components") or {})

        if isinstance(m.get("selection_components"), dict):
            components.update(m.get("selection_components") or {})

        day = m.get("day", "?")
        slot = m.get("slot", "?")
        meal_type = str(m.get("meal_type", "unknown") or "unknown")

        score = safe_float(m.get("score"))
        portion = safe_float(m.get("portion_score"))
        macro_fit = safe_float(m.get("slot_macro_fit"))

        tier = str(
            m.get("tier")
            or m.get("selection_tier")
            or components.get("selection_tier")
            or "unknown"
        )

        reason = str(
            m.get("selection_tier_reason")
            or m.get("selection_quality_reason")
            or m.get("tier_reason")
            or m.get("quality_reason")
            or components.get("selection_tier_reason")
            or components.get("selection_quality_reason")
            or components.get("tier_reason")
            or components.get("quality_reason")
            or ""
        )

        score_before_ceiling = m.get("score_before_low_score_ceiling")

        if score_before_ceiling is None:
            score_before_ceiling = m.get("score_before_ceiling")

        if score_before_ceiling is None:
            score_before_ceiling = components.get("score_before_low_score_ceiling")

        if score_before_ceiling is None:
            score_before_ceiling = components.get("score_before_ceiling")

        if score_before_ceiling is None:
            score_before_text = "-"
        else:
            try:
                score_before_text = f"{float(score_before_ceiling):.4f}"
            except Exception:
                score_before_text = str(score_before_ceiling)

        low_score_policy_applied = bool(
            m.get(
                "low_score_policy_applied",
                components.get("low_score_policy_applied", False),
            )
        )

        low_score_reason = str(
            m.get("low_score_policy_reason")
            or m.get("low_score_reason")
            or components.get("low_score_policy_reason")
            or components.get("low_score_reason")
            or ""
        )

        main_carb = (
            m.get("main_carb")
            or components.get("main_carb")
            or "None"
        )

        name = str(m.get("name", "unknown") or "unknown")

        print(
            f"day={day} slot={slot} "
            f"type={meal_type:<10s} "
            f"score={score:.4f} "
            f"before={score_before_text:<7s} "
            f"portion={portion:.4f} "
            f"macro_fit={macro_fit:.4f} "
            f"tier={tier:<9s} "
            f"reason={reason:<36s} "
            f"low_cap={str(low_score_policy_applied):<5s} "
            f"low_reason={low_score_reason:<22s} "
            f"carb={str(main_carb):<12s} "
            f"| {name}"
        )

    print_subheader("PROBLEMS")
    if not problems:
        print("  no problems detected")
    else:
        max_items = max(top_n * 2, 20)
        for p in problems[:max_items]:
            print(f"  [{p.get('severity')}] {p.get('type')} | {p}")

        if len(problems) > max_items:
            print(f"  ... {len(problems) - max_items} more")

    print_subheader("RECOMMENDATIONS")
    for item in recommendations:
        print(f"  - {item}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Food MealPlanner quality analytics report",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=safe_int(os.getenv("AI_FOOD_REPORT_DAYS", os.getenv("AI_FOOD_PROD_DAYS", 7)), 7),
        help="Number of days to generate",
    )

    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=safe_int(
            os.getenv("AI_FOOD_REPORT_CANDIDATES", os.getenv("AI_FOOD_PROD_CANDIDATES", 80)),
            80,
        ),
        help="Candidate limit for MealPlanner",
    )

    parser.add_argument(
        "--profiles",
        type=int,
        default=safe_int(
            os.getenv("AI_FOOD_REPORT_PROFILES", os.getenv("AI_FOOD_PROD_PROFILES", 2)),
            2,
        ),
        help="How many default profiles to test",
    )

    parser.add_argument(
        "--top-n",
        type=int,
        default=safe_int(os.getenv("AI_FOOD_REPORT_TOP_N", 15), 15),
        help="How many top items to print in counters",
    )

    parser.add_argument(
        "--json-out",
        type=str,
        default=os.getenv(
            "AI_FOOD_REPORT_JSON",
            str(REPORTS_DIR / "plan_quality_report.json"),
        ),
        help="Where to save JSON report",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        default=os.getenv("AI_FOOD_REPORT_STRICT", "0").strip() in {"1", "true", "yes"},
        help="Raise AssertionError if critical quality problems exist",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    
    os.environ.setdefault("AI_FOOD_MAX_OPTIMIZED_PER_SLOT", "12")
    os.environ.setdefault("AI_FOOD_PORTION_CACHE", "1")
    os.environ.setdefault("AI_FOOD_PORTION_MAX_CANDIDATES", "360")

    print_header("AI FOOD PLAN QUALITY REPORT")
    print_metric("PROJECT_ROOT", PROJECT_ROOT)
    print_metric("DATA_DIR", DATA_DIR)
    print_metric("days", args.days)
    print_metric("candidate_limit", args.candidate_limit)
    print_metric("profiles", args.profiles)
    print_metric("json_out", args.json_out)
    print_metric("strict", args.strict)

    planner = init_meal_planner()
    profiles = load_profiles(limit=args.profiles)

    full_report: Dict[str, Any] = {
        "project_root": str(PROJECT_ROOT),
        "data_dir": str(DATA_DIR),
        "settings": {
            "days": args.days,
            "candidate_limit": args.candidate_limit,
            "profiles": args.profiles,
            "strict": args.strict,
            "env": {
                "AI_FOOD_MAX_OPTIMIZED_PER_SLOT": os.getenv("AI_FOOD_MAX_OPTIMIZED_PER_SLOT"),
                "AI_FOOD_PORTION_CACHE": os.getenv("AI_FOOD_PORTION_CACHE"),
                "AI_FOOD_PORTION_MAX_CANDIDATES": os.getenv("AI_FOOD_PORTION_MAX_CANDIDATES"),
                "AI_FOOD_PROD_DAYS": os.getenv("AI_FOOD_PROD_DAYS"),
                "AI_FOOD_PROD_CANDIDATES": os.getenv("AI_FOOD_PROD_CANDIDATES"),
                "AI_FOOD_PROD_PROFILES": os.getenv("AI_FOOD_PROD_PROFILES"),
            },
        },
        "profiles": [],
    }

    total_critical = 0
    total_warnings = 0

    for profile in profiles:
        profile = dict(profile)
        profile["days"] = args.days

        print_header(f"BUILD PLAN: {profile.get('name', profile.get('goal'))}")

        start = time.perf_counter()
        plan = build_plan_compatible(
            planner=planner,
            profile=profile,
            days=args.days,
            candidate_limit=args.candidate_limit,
        )
        elapsed = time.perf_counter() - start

        report = analyze_plan(
            profile=profile,
            plan_result=plan,
            elapsed_s=elapsed,
        )

        print_profile_report(report, top_n=args.top_n)

        full_report["profiles"].append(
            {
                "input_profile": profile,
                **report,
            }
        )

        total_critical += safe_int(report["summary"].get("critical_count"))
        total_warnings += safe_int(report["summary"].get("warning_count"))

    full_report["summary"] = {
        "profiles_tested": len(full_report["profiles"]),
        "total_critical": total_critical,
        "total_warnings": total_warnings,
        "status": "FAILED" if total_critical else "OK",
    }

    out_path = Path(args.json_out)
    ensure_dir(out_path.resolve().parent)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2, default=json_default)

    print_header("FINAL SUMMARY")
    print_metric("profiles_tested", len(full_report["profiles"]))
    print_metric("total_critical", total_critical)
    print_metric("total_warnings", total_warnings)
    print_metric("json_saved", out_path)

    if args.strict and total_critical:
        raise AssertionError(f"PLAN QUALITY REPORT FAILED: {total_critical} critical problem(s)")

    print()
    print("DONE")


if __name__ == "__main__":
    main()
