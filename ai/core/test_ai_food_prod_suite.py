"""
AI Food — production-level integration and quality test suite.

Куда положить:
    AI Food/ai/core/test_ai_food_prod_suite.py

Как запускать из корня проекта:
    python -m ai.core.test_ai_food_prod_suite

Опциональные настройки:
    set AI_FOOD_PROD_DAYS=3
    set AI_FOOD_PROD_CANDIDATES=80
    set AI_FOOD_STRICT=1

Что проверяет:
- JSON-конфиги prod-уровня;
- recipes.json prod-схему;
- покрытие canonical_name в nutrition_db / food_groups / aliases;
- integrity recipe embeddings / FAISS index;
- NutritionEngine cooked/raw пересчёт;
- PortionOptimizer;
- RecipeSearch качество поиска;
- MealPlanner реальный multi-day pipeline;
- регрессию "rice 3/3";
- регрессию "breakfast выбирает rice bowl/chili/curry";
- аллергии/исключения;
- структуру components/debug/rerank.
"""
from __future__ import annotations

import inspect
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# =============================================================================
# PATHS
# =============================================================================

def _find_project_root() -> Path:
    candidates: List[Path] = []

    try:
        here = Path(__file__).resolve()
        candidates.extend([here.parent, *here.parents])
    except Exception:
        pass

    cwd = Path.cwd().resolve()
    candidates.extend([cwd, *cwd.parents])

    seen = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if (p / "ai").exists() and (p / "ai").is_dir():
            return p

    raise RuntimeError(
        "Не удалось найти PROJECT_ROOT. Запускай тест из корня проекта: "
        "python -m ai.core.test_ai_food_prod_suite"
    )


PROJECT_ROOT = _find_project_root()
AI_DIR = PROJECT_ROOT / "ai"
DATA_DIR = AI_DIR / "data"
LLM_DIR = AI_DIR / "llm"
RECIPES_DIR = AI_DIR / "recipes"

RECIPES_JSON = RECIPES_DIR / "recipes.json"
RECIPE_EMBEDDINGS = RECIPES_DIR / "recipe_embeddings.npy"
RECIPE_INDEX = RECIPES_DIR / "recipe_index.faiss"

STRICT = os.getenv("AI_FOOD_STRICT", "1").strip() not in ("0", "false", "False", "no", "NO")
DAYS = int(os.getenv("AI_FOOD_PROD_DAYS", "1"))
CANDIDATE_LIMIT = int(os.getenv("AI_FOOD_PROD_CANDIDATES", "20"))
FULL_PIPELINE_PROFILES = int(os.getenv("AI_FOOD_PROD_PROFILES", "1"))



# =============================================================================
# TEST REPORT
# =============================================================================

@dataclass
class TestReport:
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def check(self, condition: bool, message: str, *, warn: bool = False) -> None:
        if condition:
            return
        if warn:
            self.warn(message)
        else:
            self.fail(message)

    def section(self, title: str) -> None:
        print("\n" + "=" * 96)
        print(title)
        print("=" * 96)

    def print_summary(self) -> None:
        print("\n" + "=" * 96)
        print("PROD TEST SUMMARY")
        print("=" * 96)

        if self.metrics:
            print("\nMetrics:")
            for k, v in self.metrics.items():
                print(f"  {k}: {v}")

        if self.warnings:
            print(f"\nWARNINGS: {len(self.warnings)}")
            for i, w in enumerate(self.warnings[:40], 1):
                print(f"  W{i:02d}. {w}")
            if len(self.warnings) > 40:
                print(f"  ... and {len(self.warnings) - 40} more warnings")

        if self.failures:
            print(f"\nFAILURES: {len(self.failures)}")
            for i, f in enumerate(self.failures[:60], 1):
                print(f"  F{i:02d}. {f}")
            if len(self.failures) > 60:
                print(f"  ... and {len(self.failures) - 60} more failures")
        else:
            print("\nALL PROD TESTS PASSED")


# =============================================================================
# HELPERS
# =============================================================================

def load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_json(filename: str, *, required_in_data: bool = False) -> Optional[Path]:
    if required_in_data:
        p = DATA_DIR / filename
        return p if p.exists() else None

    candidates = [
        DATA_DIR / filename,
        LLM_DIR / filename,
        RECIPES_DIR / filename,
        AI_DIR / filename,
        PROJECT_ROOT / filename,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def normalize_token(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = s.replace("\\", "/")
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("&", " and ")
    s = s.replace("/", " or ")
    s = re.sub(r"[^a-z0-9а-яё]+", "_", s, flags=re.IGNORECASE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def tokenize_text(value: Any) -> List[str]:
    s = normalize_token(value)
    return [p for p in s.split("_") if p]


def flatten_strings(obj: Any) -> List[str]:
    if obj is None:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(flatten_strings(v))
        return out
    if isinstance(obj, (list, tuple, set)):
        out = []
        for v in obj:
            out.extend(flatten_strings(v))
        return out
    return [str(obj)]


def recipe_text(recipe: Dict[str, Any]) -> str:
    parts = [
        recipe.get("name", ""),
        recipe.get("title", ""),
        recipe.get("dish_name", ""),
        recipe.get("cuisine", ""),
    ]

    sp = recipe.get("search_profile")
    if isinstance(sp, dict):
        parts.append(sp.get("embedding_text", ""))

    parts.extend(flatten_strings(recipe.get("ingredients", [])))
    parts.extend(flatten_strings(recipe.get("ingredients_detail", [])))
    return " ".join(str(p) for p in parts if p)


def ingredient_names(recipe: Dict[str, Any]) -> List[str]:
    names: List[str] = []

    details = recipe.get("ingredients_detail")
    if isinstance(details, list) and details:
        for item in details:
            if isinstance(item, dict):
                names.append(
                    str(
                        item.get("canonical_name")
                        or item.get("name")
                        or item.get("ingredient")
                        or ""
                    )
                )
            elif isinstance(item, str):
                names.append(item)

    ingredients = recipe.get("ingredients")
    if isinstance(ingredients, list):
        for item in ingredients:
            if isinstance(item, dict):
                names.append(str(item.get("name") or item.get("canonical_name") or ""))
            elif isinstance(item, str):
                names.append(item)

    return [normalize_token(x) for x in names if normalize_token(x)]


def recipe_has_any(recipe: Dict[str, Any], keywords: Sequence[str]) -> bool:
    text = normalize_token(recipe_text(recipe))
    return any(normalize_token(k) in text for k in keywords)



def looks_like_dessert_or_sweet_candidate(
    recipe: Dict[str, Any],
    keywords: Sequence[str],
    *,
    query: str = "",
) -> bool:
    """
    Более точная проверка сладкого/десертов для RecipeSearch quality-тестов.

    Почему не используем простое substring matching:
    - "Chicken Pot Pie" / "Shepherd's Pie" — это main dish, а не десерт.
    - Pancakes/crepes могут быть нормальным breakfast-кандидатом, но плохим
      кандидатом для lunch/dinner main-meal запросов.
    """
    name = normalize_token(recipe.get("name") or recipe.get("title") or "")
    text = normalize_token(recipe_text(recipe))
    query_norm = normalize_token(query)

    savory_pie_exceptions = {
        "pot_pie",
        "chicken_pot_pie",
        "turkey_pot_pie",
        "shepherd_pie",
        "shepherds_pie",
        "cottage_pie",
        "fish_pie",
        "meat_pie",
        "steak_pie",
        "chicken_pie",
    }

    if any(x in name or x in text for x in savory_pie_exceptions):
        return False

    breakfast_query = any(x in query_norm for x in {"breakfast", "brunch"})

    hard_dessert_terms = {
        "cake",
        "cookie",
        "cookies",
        "brownie",
        "brownies",
        "cheesecake",
        "mousse",
        "ice_cream",
        "mochi",
        "pryaniki",
        "medovik",
        "dessert",
        "candy",
        "chocolate_chip",
        "key_lime_pie",
        "apple_pie",
        "pumpkin_pie",
        "berry_pie",
        "sweet_pie",
    }

    if any(term in text for term in hard_dessert_terms):
        return True

    # Для breakfast pancakes/crepes допустимы, для main-meal запросов — нет.
    breakfast_sweets = {"pancake", "pancakes", "crepe", "crepes", "syrup", "glaze"}
    if not breakfast_query and any(term in text for term in breakfast_sweets):
        return True

    # Fallback на входной список, но без опасного blanket "pie".
    safe_keywords = [k for k in keywords if normalize_token(k) not in {"pie", "pancakes", "crepes"}]
    return recipe_has_any(recipe, safe_keywords)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        if math.isfinite(x):
            return x
        return default
    except Exception:
        return default


def approx(value: float, target: float, tolerance: float) -> bool:
    return abs(value - target) <= tolerance


def call_flexible(func: Any, **kwargs: Any) -> Any:
    """
    Вызывает метод, передавая только те kwargs, которые реально есть в сигнатуре.
    Нужно, чтобы тесты переживали мелкие изменения API.
    """
    sig = inspect.signature(func)
    accepted = {}
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

    if has_varkw:
        accepted = kwargs
    else:
        for k, v in kwargs.items():
            if k in sig.parameters:
                accepted[k] = v

    return func(**accepted)


def get_components(candidate_or_meal: Dict[str, Any]) -> Dict[str, Any]:
    comps = candidate_or_meal.get("components")
    if isinstance(comps, dict):
        return comps

    rerank = candidate_or_meal.get("rerank_components")
    if isinstance(rerank, dict):
        return rerank

    src = candidate_or_meal.get("source")
    if isinstance(src, dict):
        comps = src.get("rerank_components") or src.get("components")
        if isinstance(comps, dict):
            return comps

    return {}


def get_main_carb(candidate_or_meal: Dict[str, Any]) -> Optional[str]:
    comps = get_components(candidate_or_meal)
    carb = comps.get("main_carb") or candidate_or_meal.get("main_carb")
    if carb:
        return normalize_token(carb)

    names = ingredient_names(candidate_or_meal)
    rules = load_json(DATA_DIR / "meal_planner_rules.json", {})
    groups = rules.get("main_carb_groups", {}) if isinstance(rules, dict) else {}

    for group_name, group_items in groups.items():
        group_norm = {normalize_token(x) for x in group_items}
        if any(n in group_norm for n in names):
            return normalize_token(group_name)

    return None


def is_score_finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except Exception:
        return False


# =============================================================================
# USER PROFILE FOR PROD TESTS
# =============================================================================

class ProdTestUserProfile:
    def __init__(
        self,
        *,
        goal: str = "balanced",
        meals_per_day: int = 3,
        target_calories: int = 2000,
        protein_target_g: float = 120.0,
        fat_target_g: float = 60.0,
        preferred_ingredients: Optional[List[str]] = None,
        disliked_ingredients: Optional[List[str]] = None,
        excluded_ingredients: Optional[List[str]] = None,
        allergies: Optional[List[str]] = None,
    ):
        self.goal = goal
        self.meals_per_day = meals_per_day
        self.target_calories = target_calories

        self.age = 25
        self.sex = "male"
        self.height_cm = 185
        self.weight_kg = 70
        self.activity_level = "moderate"

        self.protein_target_g = protein_target_g
        self.fat_target_g = fat_target_g
        self.carb_limit_g = None

        self.allergies = allergies or []
        self.preferred_ingredients = preferred_ingredients or []
        self.disliked_ingredients = disliked_ingredients or []
        self.excluded_ingredients = excluded_ingredients or []
        self.recent_meals: List[Dict[str, Any]] = []

    def add_meal(self, ingredients: Iterable[Any]) -> None:
        normalized = []
        for ing in ingredients:
            if isinstance(ing, dict):
                normalized.append(normalize_token(ing.get("name") or ing.get("canonical_name") or ""))
            else:
                normalized.append(normalize_token(ing))
        self.recent_meals.append({"ingredients": [x for x in normalized if x]})
        if len(self.recent_meals) > 30:
            self.recent_meals.pop(0)

    def get_recent_ingredients(self) -> set:
        result = set()
        for meal in self.recent_meals:
            result.update(meal.get("ingredients", []))
        return result


# =============================================================================
# IMPORTS / FACTORIES
# =============================================================================

def import_runtime(report: TestReport) -> Dict[str, Any]:
    report.section("IMPORT RUNTIME MODULES")

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    runtime: Dict[str, Any] = {}

    imports = {
        "NutritionEngine": "from ai.llm.nutrition_engine import NutritionEngine",
        "MealPlanner": "from ai.core.meal_planner import MealPlanner",
        "PortionOptimizer": "from ai.core.decision.portion_optimizer import PortionOptimizer",
        "SafetyChecker": "from ai.core.decision.safety_checker import SafetyChecker",
        "PreferenceScorer": "from ai.core.decision.preference_scorer import PreferenceScorer",
        "DiversityEngine": "from ai.core.decision.diversity_engine import DiversityEngine",
        "SubstitutionEngine": "from ai.core.decision.substitution_engine import SubstitutionEngine",
        "RecipeSearch": "from ai.recipes.recipe_search import RecipeSearch",
    }

    for name, stmt in imports.items():
        try:
            namespace: Dict[str, Any] = {}
            exec(stmt, namespace)
            runtime[name] = namespace[name]
            print(f"OK import {name}")
        except Exception as e:
            report.fail(f"Не импортируется {name}: {type(e).__name__}: {e}")

    return runtime


def make_recipe_search(runtime: Dict[str, Any], report: TestReport) -> Any:
    RecipeSearch = runtime.get("RecipeSearch")
    if RecipeSearch is None:
        return None

    attempts = [
        {},
        {
            "recipes_path": RECIPES_JSON,
            "index_path": RECIPE_INDEX,
            "embeddings_path": RECIPE_EMBEDDINGS,
        },
        {
            "recipes_file": RECIPES_JSON,
            "index_file": RECIPE_INDEX,
            "embeddings_file": RECIPE_EMBEDDINGS,
        },
    ]

    last_error = None
    for kwargs in attempts:
        try:
            obj = RecipeSearch(**kwargs)
            print(f"OK RecipeSearch init with kwargs={list(kwargs.keys())}")
            return obj
        except TypeError as e:
            last_error = e
        except Exception as e:
            last_error = e
            break

    report.fail(f"RecipeSearch не инициализируется: {type(last_error).__name__}: {last_error}")
    return None


def make_planner(runtime: Dict[str, Any], report: TestReport) -> Tuple[Any, Any, Any]:
    NutritionEngine = runtime.get("NutritionEngine")
    MealPlanner = runtime.get("MealPlanner")
    PortionOptimizer = runtime.get("PortionOptimizer")

    if not NutritionEngine or not MealPlanner or not PortionOptimizer:
        return None, None, None

    try:
        engine = NutritionEngine()
    except Exception as e:
        report.fail(f"NutritionEngine не создаётся: {type(e).__name__}: {e}")
        return None, None, None

    try:
        optimizer = PortionOptimizer(engine)
    except Exception as e:
        report.fail(f"PortionOptimizer не создаётся: {type(e).__name__}: {e}")
        return None, engine, None

    recipe_search = make_recipe_search(runtime, report)
    if recipe_search is None:
        return None, engine, optimizer

    def maybe(cls_name: str):
        cls = runtime.get(cls_name)
        if cls is None:
            return None
        try:
            return cls()
        except Exception as e:
            report.warn(f"{cls_name} не создан, тесты продолжат без него: {type(e).__name__}: {e}")
            return None

    kwargs = dict(
        recipe_search=recipe_search,
        nutrition_engine=engine,
        safety_checker=maybe("SafetyChecker"),
        preference_scorer=maybe("PreferenceScorer"),
        diversity_engine=maybe("DiversityEngine"),
        substitution_engine=maybe("SubstitutionEngine"),
        portion_optimizer=optimizer,
        llm=None,
    )

    try:
        planner = call_flexible(MealPlanner, **kwargs)
    except TypeError:
        try:
            planner = MealPlanner(**kwargs)
        except Exception as e:
            report.fail(f"MealPlanner не создаётся: {type(e).__name__}: {e}")
            return None, engine, optimizer
    except Exception as e:
        report.fail(f"MealPlanner не создаётся: {type(e).__name__}: {e}")
        return None, engine, optimizer

    print("OK MealPlanner initialized")
    return planner, engine, optimizer


# =============================================================================
# TESTS — DATA CONFIG
# =============================================================================

def test_data_config(report: TestReport) -> Dict[str, Any]:
    report.section("TEST DATA CONFIGS")

    required_data_files = [
        "meal_planner_rules.json",
        "portion_rules.json",
        "food_groups.json",
        "category_rules.json",
        "satiety_rules.json",
        "food_physics.json",
        "food_aliases.json",
    ]

    loaded: Dict[str, Any] = {}
    for filename in required_data_files:
        path = DATA_DIR / filename
        report.check(path.exists(), f"Нет prod-файла: {path}")
        if path.exists():
            try:
                loaded[filename] = load_json(path, {})
                report.check(isinstance(loaded[filename], dict), f"{filename} должен быть JSON object/dict")
                print(f"OK {filename}: keys={len(loaded[filename])}")
            except Exception as e:
                report.fail(f"{filename} не читается как JSON: {type(e).__name__}: {e}")

    rules = loaded.get("meal_planner_rules.json", {})
    if isinstance(rules, dict):
        for key in [
            "schema_version",
            "main_carb_groups",
            "main_carb_repeat_policy",
            "meal_type_rules",
            "recipe_quality_rules",
            "meal_structure_rules",
            "goal_rules",
            "slot_query_rules",
        ]:
            report.check(key in rules, f"meal_planner_rules.json: нет ключа {key}")

        carb_groups = rules.get("main_carb_groups", {})
        report.check(isinstance(carb_groups, dict), "main_carb_groups должен быть dict")
        if isinstance(carb_groups, dict):
            report.check(len(carb_groups) >= 8, "main_carb_groups должен покрывать минимум 8 групп углеводов")
            reverse: Dict[str, List[str]] = defaultdict(list)
            for group, items in carb_groups.items():
                report.check(isinstance(items, list) and items, f"main_carb_groups.{group} должен быть непустым list")
                for item in items if isinstance(items, list) else []:
                    report.check(isinstance(item, str), f"main_carb_groups.{group}: item должен быть str, got {type(item)}")
                    reverse[normalize_token(item)].append(group)

            duplicates = {item: groups for item, groups in reverse.items() if len(groups) > 1}
            if duplicates:
                sample = dict(list(duplicates.items())[:10])
                report.warn(f"Некоторые carb items лежат в нескольких группах: {sample}")

        repeat = rules.get("main_carb_repeat_policy", {})
        report.check(isinstance(repeat, dict), "main_carb_repeat_policy должен быть dict")
        if isinstance(repeat, dict):
            for key in [
                "enabled",
                "allow_same_carb_per_day",
                "same_carb_first_repeat_penalty",
                "same_carb_additional_repeat_penalty",
                "max_penalty",
                "hard_block_after_repeats",
            ]:
                report.check(key in repeat, f"main_carb_repeat_policy: нет ключа {key}")

        meal_type_rules = rules.get("meal_type_rules", {})
        report.check(isinstance(meal_type_rules, dict), "meal_type_rules должен быть dict")
        for meal_type in ["breakfast", "lunch", "dinner", "snack"]:
            cfg = meal_type_rules.get(meal_type)
            report.check(isinstance(cfg, dict), f"meal_type_rules.{meal_type} должен быть dict, а не {type(cfg).__name__}")
            if isinstance(cfg, dict):
                for key in [
                    "positive_keywords",
                    "negative_keywords",
                    "positive_bonus",
                    "max_positive_bonus",
                    "negative_penalty",
                    "max_penalty",
                ]:
                    report.check(key in cfg, f"meal_type_rules.{meal_type}: нет ключа {key}")
                report.check(
                    isinstance(cfg.get("positive_keywords"), list),
                    f"meal_type_rules.{meal_type}.positive_keywords должен быть list"
                )
                report.check(
                    isinstance(cfg.get("negative_keywords"), list),
                    f"meal_type_rules.{meal_type}.negative_keywords должен быть list"
                )

    return loaded


# =============================================================================
# TESTS — RECIPES SCHEMA / COVERAGE
# =============================================================================

def test_recipes_schema_and_coverage(report: TestReport) -> List[Dict[str, Any]]:
    report.section("TEST RECIPES.JSON PROD SCHEMA AND COVERAGE")

    report.check(RECIPES_JSON.exists(), f"Нет recipes.json: {RECIPES_JSON}")
    if not RECIPES_JSON.exists():
        return []

    try:
        recipes = load_json(RECIPES_JSON, [])
    except Exception as e:
        report.fail(f"recipes.json не читается: {type(e).__name__}: {e}")
        return []

    report.check(isinstance(recipes, list), "recipes.json должен быть list[recipe]")
    if not isinstance(recipes, list):
        return []

    report.metrics["recipes_count"] = len(recipes)
    print(f"recipes count: {len(recipes)}")
    report.check(len(recipes) >= 250, f"В recipes.json слишком мало рецептов для prod: {len(recipes)} < 250")

    ids = [r.get("id") for r in recipes if isinstance(r, dict) and r.get("id")]
    if ids:
        dup_ids = [k for k, v in Counter(ids).items() if v > 1]
        report.check(not dup_ids, f"Дубли id в recipes.json: {dup_ids[:20]}")
        report.check(len(ids) == len(recipes), f"Не у всех рецептов есть id: {len(ids)}/{len(recipes)}")
    else:
        report.fail("В prod recipes.json у рецептов должны быть id. Сейчас id не найдены.")

    bad_name = []
    bad_ingredients = []
    bad_detail = []
    bad_grams = []
    bad_servings = []
    bad_search_profile = []
    bad_nutrition_layer = []
    bad_data_quality = []
    bad_total_weight = []

    unique_canonicals: Counter[str] = Counter()
    role_counter: Counter[str] = Counter()
    amount_source_counter: Counter[str] = Counter()

    for idx, recipe in enumerate(recipes):
        if not isinstance(recipe, dict):
            bad_name.append((idx, "not dict"))
            continue

        name = str(recipe.get("name") or recipe.get("title") or "").strip()
        rid = recipe.get("id", f"index:{idx}")

        if not name:
            bad_name.append(rid)

        ingredients = recipe.get("ingredients")
        if not isinstance(ingredients, list) or not ingredients:
            bad_ingredients.append(rid)

        details = recipe.get("ingredients_detail")
        if not isinstance(details, list) or not details:
            bad_detail.append(rid)
        else:
            grams_sum = 0.0
            for item in details:
                if not isinstance(item, dict):
                    bad_detail.append((rid, "detail item not dict"))
                    continue

                canonical = normalize_token(item.get("canonical_name") or item.get("name"))
                if not canonical:
                    bad_detail.append((rid, "empty canonical_name"))
                else:
                    unique_canonicals[canonical] += 1

                grams = item.get("grams")
                grams_f = safe_float(grams, -1)
                if grams_f <= 0:
                    bad_grams.append((rid, canonical, grams))
                else:
                    grams_sum += grams_f

                role = normalize_token(item.get("role") or "")
                if role:
                    role_counter[role] += 1

                amount_source = normalize_token(item.get("amount_source") or "")
                if amount_source:
                    amount_source_counter[amount_source] += 1

            total_weight = safe_float(recipe.get("total_weight_g"), -1)
            if total_weight > 0 and grams_sum > 0:
                tolerance = max(15.0, total_weight * 0.08)
                if abs(total_weight - grams_sum) > tolerance:
                    bad_total_weight.append((rid, round(total_weight, 1), round(grams_sum, 1)))

        servings = recipe.get("servings")
        serving_model = recipe.get("serving_model")
        if servings is None and not isinstance(serving_model, dict):
            bad_servings.append(rid)

        sp = recipe.get("search_profile")
        embedding_text = ""
        if isinstance(sp, dict):
            embedding_text = str(sp.get("embedding_text") or "").strip()
        if len(embedding_text) < 30:
            bad_search_profile.append(rid)

        nutrition = recipe.get("nutrition")
        if not isinstance(nutrition, dict):
            bad_nutrition_layer.append(rid)

        data_quality = recipe.get("data_quality")
        if not isinstance(data_quality, dict):
            bad_data_quality.append(rid)

    def aggregate_check(items: list, message: str, *, fail_over: int = 0, warn: bool = False) -> None:
        if len(items) > fail_over:
            sample = items[:12]
            if warn:
                report.warn(f"{message}: count={len(items)}, sample={sample}")
            else:
                report.fail(f"{message}: count={len(items)}, sample={sample}")

    aggregate_check(bad_name, "Рецепты без name")
    aggregate_check(bad_ingredients, "Рецепты без ingredients")
    aggregate_check(bad_detail, "Рецепты без ingredients_detail")
    aggregate_check(bad_grams, "ingredients_detail с плохой grams")
    aggregate_check(bad_servings, "Рецепты без servings или serving_model")
    aggregate_check(bad_search_profile, "Рецепты без search_profile.embedding_text >= 30 символов")
    aggregate_check(bad_nutrition_layer, "Рецепты без nutrition-слоя")
    aggregate_check(bad_data_quality, "Рецепты без data_quality")
    aggregate_check(bad_total_weight, "total_weight_g не совпадает с суммой grams", warn=True)

    report.metrics["unique_canonical_ingredients"] = len(unique_canonicals)
    report.metrics["top_roles"] = dict(role_counter.most_common(10))
    report.metrics["amount_sources"] = dict(amount_source_counter.most_common(10))

    print(f"unique canonical ingredients: {len(unique_canonicals)}")
    print("top roles:", role_counter.most_common(10))
    print("amount sources:", amount_source_counter.most_common(10))

    # Coverage against nutrition_db, food_groups, aliases.
    nutrition_path = find_json("nutrition_db.json")
    food_groups_path = find_json("food_groups.json", required_in_data=True)
    aliases_path = find_json("food_aliases.json", required_in_data=True)

    nutrition_db = load_json(nutrition_path, {}) if nutrition_path else {}
    food_groups = load_json(food_groups_path, {}) if food_groups_path else {}
    aliases = load_json(aliases_path, {}) if aliases_path else {}

    alias_values = {}
    if isinstance(aliases, dict):
        for k, v in aliases.items():
            alias_values[normalize_token(k)] = normalize_token(v)

    def resolve_alias(name: str) -> str:
        n = normalize_token(name)
        return alias_values.get(n, n)

    canonical_set = set(unique_canonicals)
    resolved_set = {resolve_alias(x) for x in canonical_set}

    nutrition_keys = {normalize_token(k) for k in nutrition_db.keys()} if isinstance(nutrition_db, dict) else set()
    group_keys = {normalize_token(k) for k in food_groups.keys()} if isinstance(food_groups, dict) else set()

    missing_nutrition = sorted([x for x in resolved_set if x not in nutrition_keys])
    missing_groups = sorted([x for x in resolved_set if x not in group_keys])

    nutrition_coverage = 1.0
    group_coverage = 1.0

    if resolved_set:
        nutrition_coverage = 1.0 - len(missing_nutrition) / len(resolved_set)
        group_coverage = 1.0 - len(missing_groups) / len(resolved_set)

    report.metrics["nutrition_db_coverage"] = round(nutrition_coverage, 3)
    report.metrics["food_groups_coverage"] = round(group_coverage, 3)

    print(f"nutrition_db coverage: {nutrition_coverage:.3f}")
    print(f"food_groups coverage: {group_coverage:.3f}")

    report.check(
        nutrition_coverage >= 0.85,
        f"Покрытие nutrition_db слишком низкое: {nutrition_coverage:.3f}. "
        f"missing sample={missing_nutrition[:25]}"
    )
    report.check(
        group_coverage >= 0.75,
        f"Покрытие food_groups слишком низкое: {group_coverage:.3f}. "
        f"missing sample={missing_groups[:25]}"
    )

    return recipes


# =============================================================================
# TESTS — EMBEDDINGS / INDEX
# =============================================================================

def test_recipe_embeddings_integrity(report: TestReport, recipes: List[Dict[str, Any]]) -> None:
    report.section("TEST RECIPE EMBEDDINGS / FAISS INDEX INTEGRITY")

    report.check(RECIPE_EMBEDDINGS.exists(), f"Нет recipe_embeddings.npy: {RECIPE_EMBEDDINGS}")
    report.check(RECIPE_INDEX.exists(), f"Нет recipe_index.faiss: {RECIPE_INDEX}")

    if not RECIPE_EMBEDDINGS.exists():
        return

    try:
        import numpy as np
        emb = np.load(RECIPE_EMBEDDINGS)
        report.metrics["recipe_embeddings_shape"] = tuple(emb.shape)
        print("embeddings shape:", emb.shape)

        report.check(len(emb.shape) == 2, "recipe_embeddings.npy должен быть 2D массивом")
        if len(emb.shape) == 2:
            report.check(emb.shape[0] == len(recipes), f"embeddings rows != recipes count: {emb.shape[0]} != {len(recipes)}")
            report.check(emb.shape[1] >= 128, f"embedding dim выглядит слишком маленьким: {emb.shape[1]}")
            report.check(not np.isnan(emb).any(), "recipe_embeddings.npy содержит NaN")
            report.check(not np.isinf(emb).any(), "recipe_embeddings.npy содержит inf")

            norms = np.linalg.norm(emb, axis=1)
            report.metrics["embedding_norm_min"] = round(float(norms.min()), 4)
            report.metrics["embedding_norm_max"] = round(float(norms.max()), 4)
            report.metrics["embedding_norm_mean"] = round(float(norms.mean()), 4)

            # Для cosine/IP FAISS желательно, чтобы нормы были около 1.
            if norms.mean() < 0.85 or norms.mean() > 1.15:
                report.warn(
                    f"Средняя норма embedding не около 1: mean={norms.mean():.3f}. "
                    "Для IndexFlatIP обычно нужно L2-normalize."
                )

            duplicate_rows = int((norms < 1e-8).sum())
            report.check(duplicate_rows == 0, f"Есть нулевые recipe embeddings: {duplicate_rows}")

    except Exception as e:
        report.fail(f"Не удалось проверить recipe_embeddings.npy: {type(e).__name__}: {e}")

    if RECIPE_INDEX.exists():
        try:
            import faiss  # type: ignore
            index = faiss.read_index(str(RECIPE_INDEX))
            report.metrics["recipe_index_ntotal"] = int(index.ntotal)
            report.metrics["recipe_index_d"] = int(index.d)
            print(f"faiss index: ntotal={index.ntotal}, d={index.d}")

            report.check(index.ntotal == len(recipes), f"FAISS ntotal != recipes count: {index.ntotal} != {len(recipes)}")
        except Exception as e:
            report.fail(f"Не удалось прочитать FAISS index: {type(e).__name__}: {e}")


# =============================================================================
# TESTS — NUTRITION ENGINE
# =============================================================================

def test_nutrition_engine(report: TestReport, runtime: Dict[str, Any]) -> Any:
    report.section("TEST NUTRITION ENGINE")

    NutritionEngine = runtime.get("NutritionEngine")
    if NutritionEngine is None:
        return None

    try:
        engine = NutritionEngine()
    except Exception as e:
        report.fail(f"NutritionEngine не создаётся: {type(e).__name__}: {e}")
        return None

    report.check(bool(getattr(engine, "db", {})), "NutritionEngine.db пустой")
    report.check(bool(getattr(engine, "portion", getattr(engine, "portions", {}))), "NutritionEngine portion_rules не загружены", warn=True)
    report.check(bool(getattr(engine, "food_groups", {})), "NutritionEngine food_groups не загружены", warn=True)
    report.check(bool(getattr(engine, "category_rules", {})), "NutritionEngine category_rules не загружены", warn=True)

    # cooked -> raw regression for rice.
    try:
        result = engine.calculate([{"name": "rice", "grams": 250, "state": "cooked"}])
        pprint(result)

        rice_entry = engine.db.get("rice", {})
        rice_nutrition = rice_entry.get("nutrition_per_100g", rice_entry)
        rice_state = rice_entry.get("state", "raw")
        rice_factor = safe_float(rice_entry.get("cooked_weight_factor", 1.0), 1.0)

        expected_nutrition_weight = 250.0
        if rice_state == "raw" and rice_factor != 0:
            expected_nutrition_weight = 250.0 / rice_factor

        expected_calories = safe_float(rice_nutrition.get("calories")) * expected_nutrition_weight / 100.0

        report.check(approx(result.get("eaten_weight_g", 0), 250, 1), f"rice eaten_weight_g != 250: {result.get('eaten_weight_g')}")
        report.check(
            approx(result.get("nutrition_weight_g", 0), expected_nutrition_weight, 3),
            f"rice nutrition_weight_g некорректный: got={result.get('nutrition_weight_g')}, expected={expected_nutrition_weight:.1f}"
        )
        report.check(
            approx(result.get("calories", 0), expected_calories, 8),
            f"rice calories некорректные: got={result.get('calories')}, expected={expected_calories:.1f}"
        )

        if rice_state == "raw":
            report.check(
                safe_float(rice_nutrition.get("calories")) >= 300,
                "rice в nutrition_db указан state=raw, но calories < 300/100g. "
                "Похоже, в raw-запись попали cooked значения."
            )

        for key in [
            "calories", "protein", "fat", "carbs", "fiber", "sugar",
            "sodium_mg", "saturated_fat", "eaten_weight_g",
            "nutrition_weight_g", "energy_density_kcal_per_g",
            "satiety_score", "category_balance", "category_breakdown",
        ]:
            report.check(key in result, f"NutritionEngine.calculate не возвращает ключ {key}")
    except Exception as e:
        report.fail(f"NutritionEngine cooked/raw test упал: {type(e).__name__}: {e}")

    # Sample items should calculate.
    for item in ["chicken", "rice", "egg", "beef", "potato"]:
        if item not in getattr(engine, "db", {}):
            report.warn(f"{item} отсутствует в nutrition_db, sample-test пропущен")
            continue
        try:
            res = engine.calculate([{"name": item, "grams": 100}])
            report.check(res.get("calories", 0) > 0, f"{item}: calories <= 0")
            report.check(res.get("eaten_weight_g", 0) > 0, f"{item}: eaten_weight_g <= 0")
        except Exception as e:
            report.fail(f"{item}: calculate упал: {type(e).__name__}: {e}")

    return engine


# =============================================================================
# TESTS — PORTION OPTIMIZER
# =============================================================================

def test_portion_optimizer(report: TestReport, runtime: Dict[str, Any], engine: Any) -> Any:
    report.section("TEST PORTION OPTIMIZER")

    PortionOptimizer = runtime.get("PortionOptimizer")
    if PortionOptimizer is None or engine is None:
        return None

    try:
        optimizer = PortionOptimizer(engine)
    except Exception as e:
        report.fail(f"PortionOptimizer не создаётся: {type(e).__name__}: {e}")
        return None

    profile = ProdTestUserProfile(
        goal="balanced",
        target_calories=2000,
        protein_target_g=120,
        fat_target_g=60,
        preferred_ingredients=["chicken", "rice", "beef", "potato"],
    )

    recipes = [
        {
            "name": "Chicken Rice Bowl",
            "ingredients": [
                {"name": "chicken", "grams": 150, "state": "cooked"},
                {"name": "rice", "grams": 180, "state": "cooked"},
            ],
            "servings": 1,
        },
        {
            "name": "Beef Potato Meal",
            "ingredients": [
                {"name": "beef", "grams": 150, "state": "cooked"},
                {"name": "potato", "grams": 250, "state": "cooked"},
            ],
            "servings": 1,
        },
        {
            "name": "Egg Potato Breakfast",
            "ingredients": [
                {"name": "egg", "grams": 100, "state": "raw"},
                {"name": "potato", "grams": 200, "state": "cooked"},
            ],
            "servings": 1,
        },
    ]

    for recipe in recipes:
        try:
            optimized = optimizer.optimize_recipe(
                recipe=recipe,
                user_profile=profile,
                meal_type="lunch",
                slot_target_calories=800,
                slot_macro_targets={"protein_g": 48, "fat_g": 24, "carbs_g": 98},
            )
            pprint({"recipe": recipe["name"], "optimized": optimized})

            report.check(isinstance(optimized, dict), f"{recipe['name']}: optimize_recipe должен вернуть dict")
            report.check(bool(optimized.get("ingredients")), f"{recipe['name']}: optimizer не вернул ingredients")
            nutrition = optimized.get("nutrition", {})
            portion = optimized.get("portion", {})
            report.check(nutrition.get("calories", 0) > 0, f"{recipe['name']}: calories <= 0")
            report.check(portion.get("score", -1) >= 0, f"{recipe['name']}: portion score < 0")

            eaten_weight = safe_float(nutrition.get("eaten_weight_g"))
            report.check(150 <= eaten_weight <= 1200, f"{recipe['name']}: eaten_weight_g нереалистичен: {eaten_weight}")

            comps = portion.get("components", {})
            for key in ["calorie_fit", "macro_fit", "portion_feasibility", "meal_weight_score"]:
                report.check(key in comps, f"{recipe['name']}: portion.components без {key}", warn=True)

        except Exception as e:
            report.fail(f"{recipe['name']}: PortionOptimizer упал: {type(e).__name__}: {e}")

    return optimizer


# =============================================================================
# TESTS — RECIPE SEARCH QUALITY
# =============================================================================

def test_recipe_search_quality(report: TestReport, runtime: Dict[str, Any], recipes: List[Dict[str, Any]]) -> Any:
    report.section("TEST RECIPE SEARCH QUALITY")

    recipe_search = make_recipe_search(runtime, report)
    if recipe_search is None:
        return None

    dessert_keywords = [
        "cake", "cookie", "cookies", "brownie", "brownies", "mousse",
        "ice cream", "pie", "sweet", "syrup", "glaze", "pancakes",
        "crepes", "mochi", "pryaniki", "medovik"
    ]

    query_cases = [
        {
            "query": "egg breakfast high protein",
            "must_have_any_top5": ["egg", "eggs", "omelette", "breakfast", "toast", "cottage_cheese"],
            "no_dessert_top3": True,
        },
        {
            "query": "chicken rice balanced main meal",
            "must_have_any_top5": ["chicken"],
            "no_dessert_top3": True,
        },
        {
            "query": "beef pasta high protein dinner",
            "must_have_any_top5": ["beef", "pasta", "noodles"],
            "no_dessert_top3": True,
        },
        {
            "query": "weight loss chicken vegetables lean protein",
            "must_have_any_top5": ["chicken", "turkey", "cod", "vegetable", "broccoli", "carrot"],
            "no_dessert_top3": True,
        },
        {
            "query": "salmon potato dinner",
            "must_have_any_top5": ["salmon", "fish", "cod", "potato"],
            "no_dessert_top3": True,
        },
    ]

    for case in query_cases:
        query = case["query"]
        print(f"\n--- RecipeSearch query: {query!r} ---")

        try:
            try:
                results = recipe_search.search(query, top_k=20)
            except TypeError:
                results = recipe_search.search(query)

            if isinstance(results, dict):
                results = results.get("recipes") or list(results.values())

            report.check(isinstance(results, list), f"RecipeSearch({query}) должен вернуть list")
            if not isinstance(results, list):
                continue

            report.check(len(results) >= 5, f"RecipeSearch({query}) вернул мало результатов: {len(results)}")

            for i, r in enumerate(results[:10], 1):
                print(f"{i:02d}. score={r.get('score')} | {r.get('name')}")
                print("    ingredients:", ingredient_names(r)[:16])

            top5 = results[:5]
            top3 = results[:3]

            must = [normalize_token(x) for x in case["must_have_any_top5"]]
            hit = any(any(m in normalize_token(recipe_text(r)) for m in must) for r in top5)
            report.check(
                hit,
                f"RecipeSearch({query}): top5 не содержит ожидаемых терминов {must}. "
                f"top5={[r.get('name') for r in top5]}"
            )

            if case.get("no_dessert_top3"):
                desserts_top3 = [
                    r.get("name")
                    for r in top3
                    if looks_like_dessert_or_sweet_candidate(
                        r,
                        dessert_keywords,
                        query=query,
                    )
                ]
                report.check(
                    not desserts_top3,
                    f"RecipeSearch({query}): десерты/сладкое попали в top3 main-meal запроса: {desserts_top3}"
                )

            scores = [r.get("score") for r in results[:10] if r.get("score") is not None]
            report.check(all(is_score_finite(s) for s in scores), f"RecipeSearch({query}): есть не-finite score")
        except Exception as e:
            report.fail(f"RecipeSearch({query}) упал: {type(e).__name__}: {e}")

    return recipe_search


# =============================================================================
# TESTS — SLOT CANDIDATE RERANK
# =============================================================================

def test_slot_candidate_rerank(report: TestReport, planner: Any) -> None:
    report.section("TEST MEALPLANNER SLOT CANDIDATE RERANK")

    if planner is None:
        return

    if not hasattr(planner, "_fetch_slot_candidates"):
        report.warn("MealPlanner не имеет _fetch_slot_candidates; slot rerank test пропущен")
        return

    profile = ProdTestUserProfile(
        goal="balanced",
        meals_per_day=3,
        target_calories=2000,
        protein_target_g=120,
        fat_target_g=60,
        preferred_ingredients=["chicken", "turkey", "beef", "egg", "potato", "bread"],
    )

    slot_specs = [
        ("breakfast", 600.0, {"protein_g": 36.0, "fat_g": 18.0, "carbs_g": 73.5}),
        ("lunch", 800.0, {"protein_g": 48.0, "fat_g": 24.0, "carbs_g": 98.0}),
        ("dinner", 600.0, {"protein_g": 36.0, "fat_g": 18.0, "carbs_g": 73.5}),
    ]

    used_main_carbs: List[str] = []

    for slot_idx, (meal_type, slot_cal, slot_macros) in enumerate(slot_specs):
        print("\n" + "-" * 80)
        print(f"SLOT {slot_idx + 1}: {meal_type}")
        print("used_main_carbs before:", used_main_carbs)

        try:
            candidates = call_flexible(
                planner._fetch_slot_candidates,
                user_profile=profile,
                profile=profile,
                goal=profile.goal,
                meal_type=meal_type,
                slot_idx=slot_idx,
                slot_number=slot_idx,
                slot_target_calories=slot_cal,
                target_calories=slot_cal,
                slot_macro_targets=slot_macros,
                slot_target_macros=slot_macros,
                macro_targets=slot_macros,
                used_main_carbs=used_main_carbs,
                candidate_limit=20,
                top_k=20,
            )

            report.check(isinstance(candidates, list), f"_fetch_slot_candidates({meal_type}) должен вернуть list")
            if not isinstance(candidates, list):
                continue

            report.check(len(candidates) >= 5, f"_fetch_slot_candidates({meal_type}) вернул мало кандидатов: {len(candidates)}")

            for i, c in enumerate(candidates[:10], 1):
                comps = get_components(c)
                print(
                    f"{i:02d}. score={c.get('score')} rerank={c.get('rerank_score')} "
                    f"main_carb={get_main_carb(c)} | {c.get('name')}"
                )
                print("    components:", comps)

            top = candidates[0] if candidates else {}
            top_components = get_components(top)

            for c in candidates[:10]:
                comps = get_components(c)
                report.check(
                    "main_carb_hard_block" in comps or "main_carb" in comps or get_main_carb(c) is not None,
                    f"{meal_type}: candidate без main_carb debug: {c.get('name')}",
                    warn=True,
                )
                if c.get("score") is not None:
                    report.check(is_score_finite(c.get("score")), f"{meal_type}: non-finite score у {c.get('name')}")

            if meal_type == "breakfast":
                bad_breakfast_terms = [
                    "rice_bowl", "chili", "curry", "stroganoff", "bolognese",
                    "lasagna", "goulash", "pilaf", "soup"
                ]
                top5_bad = [
                    c.get("name")
                    for c in candidates[:5]
                    if any(term in normalize_token(recipe_text(c)) for term in bad_breakfast_terms)
                ]
                report.check(
                    not top5_bad,
                    f"Breakfast top5 содержит неподходящие блюда: {top5_bad}"
                )
                report.check(
                    safe_float(top_components.get("meal_type_fit"), 0.5) >= 0.5,
                    f"Breakfast top1 имеет плохой meal_type_fit: {top.get('name')} comps={top_components}"
                )

            chosen_carb = get_main_carb(top)
            if chosen_carb:
                used_main_carbs.append(chosen_carb)

        except Exception as e:
            report.fail(f"_fetch_slot_candidates({meal_type}) упал: {type(e).__name__}: {e}")

    if len(used_main_carbs) >= 3:
        c = Counter(used_main_carbs)
        report.check(
            c.most_common(1)[0][1] < 3,
            f"Регрессия main_carb 3/3 в slot simulation: {used_main_carbs}"
        )

    print("used_main_carbs after simulation:", used_main_carbs)


# =============================================================================
# TESTS — FULL MEAL PLANNER
# =============================================================================

def _plan_day_meals(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    days = plan.get("plan", [])
    meals: List[Dict[str, Any]] = []
    if isinstance(days, list):
        for day in days:
            if isinstance(day, dict) and isinstance(day.get("meals"), list):
                meals.extend(day["meals"])
    return meals


def test_meal_planner_real_pipeline(report: TestReport, planner: Any) -> None:
    report.section("TEST MEALPLANNER REAL MULTI-DAY PIPELINE")

    if planner is None:
        return

    profiles = [
        ProdTestUserProfile(
            goal="balanced",
            meals_per_day=3,
            target_calories=2000,
            protein_target_g=120,
            fat_target_g=60,
            preferred_ingredients=["chicken", "turkey", "beef", "egg", "potato", "bread"],
        ),
        ProdTestUserProfile(
            goal="weight_loss",
            meals_per_day=3,
            target_calories=1800,
            protein_target_g=130,
            fat_target_g=55,
            preferred_ingredients=["chicken", "turkey", "cod", "egg", "vegetables"],
            disliked_ingredients=["heavy_cream", "butter"],
        ),
        ProdTestUserProfile(
            goal="muscle_gain",
            meals_per_day=4,
            target_calories=2600,
            protein_target_g=145,
            fat_target_g=75,
            preferred_ingredients=["beef", "chicken", "rice", "pasta", "potato"],
        ),
        ProdTestUserProfile(
            goal="balanced",
            meals_per_day=3,
            target_calories=2000,
            protein_target_g=120,
            fat_target_g=60,
            preferred_ingredients=["chicken", "turkey", "egg", "potato", "bread"],
            excluded_ingredients=["rice", "beef"],
            allergies=["shellfish"],
        ),
    ]
    profiles = profiles[:FULL_PIPELINE_PROFILES]

    for profile in profiles:
        print("\n" + "-" * 96)
        print(f"PROFILE goal={profile.goal}, kcal={profile.target_calories}, meals/day={profile.meals_per_day}, excluded={profile.excluded_ingredients}")

        start = time.perf_counter()
        try:
            started = time.perf_counter()

            print(
                f"START build_plan: goal={profile.goal}, "
                f"days={DAYS}, candidate_limit={CANDIDATE_LIMIT}",
                flush=True,
            )

            plan = planner.build_plan(
                user_profile=profile,
                days=DAYS,
                candidate_limit=CANDIDATE_LIMIT,
                explain_with_llm=False,
            )

            elapsed = time.perf_counter() - started
            print(f"DONE build_plan: elapsed={elapsed:.2f}s", flush=True)
        except TypeError:
            plan = planner.build_plan(profile, DAYS, CANDIDATE_LIMIT, False)
        except Exception as e:
            report.fail(f"build_plan({profile.goal}) упал: {type(e).__name__}: {e}")
            continue

        elapsed = time.perf_counter() - start
        print(f"build_plan elapsed: {elapsed:.2f}s")
        pprint(plan)

        report.check(isinstance(plan, dict), f"build_plan({profile.goal}) должен вернуть dict")
        if not isinstance(plan, dict):
            continue

        report.check(plan.get("status") == "ok", f"build_plan({profile.goal}) status != ok: {plan.get('status')}")
        days = plan.get("plan", [])
        report.check(isinstance(days, list), f"build_plan({profile.goal}) plan должен быть list")
        if not isinstance(days, list):
            continue

        report.check(len(days) == DAYS, f"build_plan({profile.goal}) дней должно быть {DAYS}, got {len(days)}")

        macro_targets = plan.get("macro_targets", {})
        target_calories = safe_float(plan.get("target_calories") or profile.target_calories)

        all_recipe_names: List[str] = []
        all_main_carbs: List[str] = []

        for day in days:
            if not isinstance(day, dict):
                report.fail(f"{profile.goal}: day не dict: {day}")
                continue

            day_num = day.get("day")
            meals = day.get("meals", [])
            day_total = day.get("day_total", {})

            report.check(isinstance(meals, list), f"{profile.goal} day {day_num}: meals не list")
            if not isinstance(meals, list):
                continue

            report.check(
                len(meals) == profile.meals_per_day,
                f"{profile.goal} day {day_num}: meals count != {profile.meals_per_day}, got {len(meals)}"
            )

            calories = safe_float(day_total.get("calories"))
            protein = safe_float(day_total.get("protein"))
            fat = safe_float(day_total.get("fat"))
            carbs = safe_float(day_total.get("carbs"))

            report.check(calories > 0, f"{profile.goal} day {day_num}: calories <= 0")
            report.check(
                0.78 * target_calories <= calories <= 1.18 * target_calories,
                f"{profile.goal} day {day_num}: calories далеко от target: {calories} vs {target_calories}"
            )

            target_protein = safe_float(macro_targets.get("protein_g") or profile.protein_target_g)
            target_fat = safe_float(macro_targets.get("fat_g") or profile.fat_target_g)
            target_carbs = safe_float(macro_targets.get("carbs_g"), 0)

            report.check(
                protein >= 0.72 * target_protein,
                f"{profile.goal} day {day_num}: protein низкий: {protein} vs target {target_protein}"
            )
            report.check(
                fat <= 1.45 * max(target_fat, 1),
                f"{profile.goal} day {day_num}: fat сильно выше target: {fat} vs target {target_fat}",
                warn=(profile.goal != "weight_loss"),
            )
            if target_carbs > 0:
                report.check(
                    carbs <= 1.40 * target_carbs,
                    f"{profile.goal} day {day_num}: carbs сильно выше target: {carbs} vs target {target_carbs}",
                    warn=True,
                )

            day_names = [str(m.get("name")) for m in meals if isinstance(m, dict)]
            duplicates = [name for name, count in Counter(day_names).items() if count > 1]
            report.check(not duplicates, f"{profile.goal} day {day_num}: повторы блюд в день: {duplicates}")

            day_carbs: List[str] = []
            for meal in meals:
                if not isinstance(meal, dict):
                    continue

                name = meal.get("name", "unknown")
                all_recipe_names.append(str(name))

                ingredients = meal.get("ingredients", [])
                report.check(isinstance(ingredients, list) and ingredients, f"{profile.goal} day {day_num} {name}: нет ingredients")

                for ing in ingredients if isinstance(ingredients, list) else []:
                    if isinstance(ing, dict):
                        grams = safe_float(ing.get("grams"), -1)
                        report.check(grams > 0, f"{profile.goal} day {day_num} {name}: плохой grams в {ing}")
                    else:
                        # В prod после PortionOptimizer лучше иметь dict grams.
                        report.warn(f"{profile.goal} day {day_num} {name}: ingredient не dict с grams: {ing}")

                nutrition = meal.get("nutrition", {})
                report.check(isinstance(nutrition, dict), f"{profile.goal} day {day_num} {name}: nutrition не dict")
                if isinstance(nutrition, dict):
                    report.check(nutrition.get("calories", 0) > 0, f"{profile.goal} day {day_num} {name}: calories <= 0")
                    report.check(120 <= safe_float(nutrition.get("eaten_weight_g")) <= 1300, f"{profile.goal} day {day_num} {name}: eaten_weight_g нереалистичен")

                portion = meal.get("portion", {})
                report.check(isinstance(portion, dict), f"{profile.goal} day {day_num} {name}: нет portion dict", warn=True)
                if isinstance(portion, dict):
                    report.check(portion.get("score", -1) >= 0, f"{profile.goal} day {day_num} {name}: portion.score < 0", warn=True)

                components = get_components(meal)
                for key in ["portion_score", "retrieval", "meal_type_fit", "main_carb"]:
                    report.check(key in components, f"{profile.goal} day {day_num} {name}: components без {key}", warn=True)

                score = meal.get("score")
                report.check(score is None or is_score_finite(score), f"{profile.goal} day {day_num} {name}: non-finite score")
                if score is not None and safe_float(score) < 0.22:
                    report.warn(f"{profile.goal} day {day_num} {name}: низкий final score={score}")

                meal_type = normalize_token(meal.get("meal_type"))
                if meal_type == "breakfast":
                    mt_fit = safe_float(components.get("meal_type_fit"), 0.5)
                    mt_penalty = safe_float(components.get("meal_type_penalty"), 0.0)
                    bad_terms = [
                        "rice_bowl", "chili", "curry", "stroganoff", "bolognese",
                        "lasagna", "goulash", "pilaf", "salad", "nicoise", "niçoise",
                        "stew", "tacos", "burrito", "paella", "risotto", "pasta", "noodle"
                    ]
                    bad = any(term in normalize_token(recipe_text(meal)) for term in bad_terms)
                    report.check(
                        not (bad and (mt_fit < 0.5 or mt_penalty > 0)),
                        f"{profile.goal} day {day_num}: breakfast выглядит неподходящим: {name}, comps={components}"
                    )

                carb = get_main_carb(meal)
                if carb:
                    day_carbs.append(carb)
                    all_main_carbs.append(carb)

                # Exclusions / allergies.
                normalized_ing = set(ingredient_names(meal))
                excluded = {normalize_token(x) for x in profile.excluded_ingredients}
                forbidden_hits = sorted(normalized_ing & excluded)
                report.check(
                    not forbidden_hits,
                    f"{profile.goal} day {day_num} {name}: содержит excluded ingredients: {forbidden_hits}"
                )

            if day_carbs:
                carb_counts = Counter(day_carbs)
                report.check(
                    carb_counts.most_common(1)[0][1] < len(meals),
                    f"{profile.goal} day {day_num}: регрессия main_carb во всех приёмах: {day_carbs}"
                )
                report.check(
                    not (len(meals) >= 3 and carb_counts.get("rice", 0) >= 3),
                    f"{profile.goal} day {day_num}: регрессия rice 3/3: {day_carbs}"
                )
                report.check(
                    len(set(day_carbs)) >= min(2, len(day_carbs)),
                    f"{profile.goal} day {day_num}: плохое разнообразие main_carb: {day_carbs}"
                )

        weekly_dupes = [name for name, count in Counter(all_recipe_names).items() if count > max(1, DAYS // 2 + 1)]
        report.check(
            not weekly_dupes,
            f"{profile.goal}: слишком частые повторы блюд за {DAYS} дней: {weekly_dupes[:10]}",
            warn=True,
        )

        if elapsed > 90:
            report.warn(f"build_plan({profile.goal}) слишком долгий: {elapsed:.1f}s")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    report = TestReport()

    print("PROJECT_ROOT:", PROJECT_ROOT)
    print("DATA_DIR:", DATA_DIR)
    print("RECIPES_JSON:", RECIPES_JSON)
    print("STRICT:", STRICT)
    print("DAYS:", DAYS)
    print("CANDIDATE_LIMIT:", CANDIDATE_LIMIT)

    runtime = import_runtime(report)
    test_data_config(report)
    recipes = test_recipes_schema_and_coverage(report)
    test_recipe_embeddings_integrity(report, recipes)
    engine = test_nutrition_engine(report, runtime)
    test_portion_optimizer(report, runtime, engine)
    test_recipe_search_quality(report, runtime, recipes)

    planner, _, _ = make_planner(runtime, report)
    test_slot_candidate_rerank(report, planner)
    test_meal_planner_real_pipeline(report, planner)

    report.print_summary()

    if report.failures:
        raise AssertionError(f"PROD TESTS FAILED: {len(report.failures)} failure(s)")

    if STRICT and report.warnings:
        print("\nSTRICT MODE: warnings are shown but do not fail the suite by default.")
        print("Чтобы сделать warnings фатальными — поменяй это поведение в main().")


if __name__ == "__main__":
    main()
