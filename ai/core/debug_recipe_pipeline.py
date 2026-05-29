from __future__ import annotations

"""
debug_recipe_pipeline.py

Запуск из корня проекта AI Food:

    python -m ai.core.debug_recipe_pipeline

Что проверяет:
1. Видит ли проект recipes.json.
2. Какие ингредиенты чаще всего встречаются в рецептах.
3. Есть ли в датасете альтернативы рису: potato, pasta, noodles, oats и т.д.
4. Умеет ли твой RecipeSearch возвращать разные блюда по разным запросам.
5. Что именно попадает в MealPlanner как candidates до финального scoring.

Если RecipeSearch не получится автоматически создать, скрипт выведет список классов/функций
в ai.recipes.recipe_search, чтобы ты быстро поправил make_recipe_search().
"""

import argparse
import importlib
import inspect
import json
from collections import Counter
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_DIR = PROJECT_ROOT / "ai"
RECIPES_JSON = AI_DIR / "recipes" / "recipes.json"


DEFAULT_QUERIES = [
    "balanced",
    "balanced chicken",
    "balanced chicken rice",
    "chicken potato",
    "chicken pasta",
    "beef potato",
    "salmon potato",
    "egg breakfast",
    "high protein dinner",
    "weight loss chicken vegetables",
    "muscle gain beef pasta",
]


WATCH_INGREDIENTS = [
    "rice",
    "potato",
    "pasta",
    "noodles",
    "oats",
    "bread",
    "chicken",
    "beef",
    "salmon",
    "tuna",
    "egg",
    "shrimp",
    "broccoli",
    "carrot",
    "vegetable",
]


def normalize_name(value: Any) -> str:
    value = str(value or "").strip().lower()
    value = value.replace("-", "_")
    value = "_".join(value.split())
    return value


def ingredient_names(ingredients: Any) -> List[str]:
    result = []

    if not isinstance(ingredients, list):
        return result

    for item in ingredients:
        if isinstance(item, str):
            name = normalize_name(item)
        elif isinstance(item, dict):
            name = normalize_name(item.get("name", ""))
        else:
            name = ""

        if name:
            result.append(name)

    return result


def recipe_name(recipe: Dict[str, Any]) -> str:
    return str(
        recipe.get("name")
        or recipe.get("title")
        or recipe.get("dish_name")
        or "unknown meal"
    )


def recipe_score(recipe: Dict[str, Any]) -> float:
    try:
        return float(recipe.get("score", 0.0))
    except Exception:
        return 0.0


def load_recipes(path: Path = RECIPES_JSON) -> List[Dict[str, Any]]:
    if not path.exists():
        print(f"[ERROR] recipes.json not found: {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "recipes" in data and isinstance(data["recipes"], list):
            data = data["recipes"]
        else:
            data = list(data.values())

    if not isinstance(data, list):
        print("[ERROR] recipes.json top-level must be list or object with recipes")
        return []

    return [r for r in data if isinstance(r, dict)]


def analyze_dataset(recipes: List[Dict[str, Any]]) -> None:
    print("\n=== DATASET ANALYSIS ===")
    print(f"recipes count: {len(recipes)}")

    ingredient_counter = Counter()
    recipe_ingredient_presence = Counter()
    no_ingredients = 0

    for recipe in recipes:
        names = ingredient_names(recipe.get("ingredients", []))

        if not names:
            no_ingredients += 1

        ingredient_counter.update(names)
        recipe_ingredient_presence.update(set(names))

    print(f"recipes without ingredients: {no_ingredients}")

    print("\nTop ingredients by total occurrences:")
    for name, count in ingredient_counter.most_common(30):
        print(f"  {name:24s} {count}")

    print("\nWatch ingredients recipe presence:")
    for name in WATCH_INGREDIENTS:
        print(
            f"  {name:16s} "
            f"recipes={recipe_ingredient_presence.get(name, 0)} "
            f"total={ingredient_counter.get(name, 0)}"
        )

    print("\nRice dominance check:")
    rice_recipes = recipe_ingredient_presence.get("rice", 0)
    if recipes:
        print(f"  rice recipes ratio: {rice_recipes}/{len(recipes)} = {rice_recipes / len(recipes):.2%}")


def print_recipe_list(title: str, recipes: List[Dict[str, Any]], top_k: int = 15) -> None:
    print(f"\n=== {title} ===")

    for idx, recipe in enumerate(recipes[:top_k], start=1):
        names = ingredient_names(recipe.get("ingredients", []))
        score = recipe_score(recipe)
        has_rice = "rice" in names
        print(f"{idx:02d}. score={score:.4f} rice={has_rice} | {recipe_name(recipe)}")
        print(f"    ingredients: {names[:20]}")


def lexical_search(recipes: List[Dict[str, Any]], query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Простой baseline без embeddings.
    Нужен, чтобы понять: вообще есть ли в recipes.json блюда под запрос.
    """

    q_tokens = set(normalize_name(query).split("_"))
    scored = []

    for recipe in recipes:
        name = normalize_name(recipe_name(recipe))
        ingredients = ingredient_names(recipe.get("ingredients", []))

        text_tokens = set(name.split("_"))
        for ing in ingredients:
            text_tokens.update(ing.split("_"))

        overlap = len(q_tokens & text_tokens)
        if overlap <= 0:
            continue

        scored.append((overlap, recipe))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


def inspect_recipe_search_module() -> None:
    print("\n=== INSPECT ai.recipes.recipe_search ===")

    try:
        module = importlib.import_module("ai.recipes.recipe_search")
    except Exception as exc:
        print(f"[ERROR] Cannot import ai.recipes.recipe_search: {exc}")
        return

    public = [name for name in dir(module) if not name.startswith("_")]

    print("public names:")
    for name in public:
        obj = getattr(module, name)
        if inspect.isclass(obj) or inspect.isfunction(obj):
            try:
                sig = inspect.signature(obj)
            except Exception:
                sig = "<?>"
            print(f"  {name}{sig}")
        else:
            print(f"  {name}: {type(obj)}")


def make_recipe_search():
    """
    Пытается автоматически создать твой RecipeSearch.

    Если не получилось:
    - посмотри вывод inspect_recipe_search_module();
    - поправь эту функцию под реальный конструктор твоего recipe_search.py.
    """

    module = importlib.import_module("ai.recipes.recipe_search")

    class_names = [
        "RecipeSearch",
        "RecipeSearcher",
        "SemanticRecipeSearch",
        "RecipeSemanticSearch",
    ]

    for class_name in class_names:
        cls = getattr(module, class_name, None)
        if cls is None or not inspect.isclass(cls):
            continue

        attempts = [
            {},
            {
                "recipes_path": str(AI_DIR / "recipes" / "recipes.json"),
                "index_path": str(AI_DIR / "recipes" / "recipe_index.faiss"),
                "embeddings_path": str(AI_DIR / "recipes" / "recipe_embeddings.npy"),
            },
            {
                "recipe_path": str(AI_DIR / "recipes" / "recipes.json"),
                "index_path": str(AI_DIR / "recipes" / "recipe_index.faiss"),
                "embedding_path": str(AI_DIR / "recipes" / "recipe_embeddings.npy"),
            },
        ]

        for kwargs in attempts:
            try:
                return cls(**kwargs)
            except TypeError:
                continue
            except Exception as exc:
                print(f"[WARN] {class_name} failed with {kwargs}: {exc}")
                continue

    for fn_name in ["search", "search_recipes", "recipe_search"]:
        fn = getattr(module, fn_name, None)
        if fn and inspect.isfunction(fn):
            class FunctionAdapter:
                def search(self, query, top_k=10):
                    try:
                        return fn(query, top_k=top_k)
                    except TypeError:
                        return fn(query)

            return FunctionAdapter()

    raise RuntimeError(
        "Cannot auto-create RecipeSearch. Check ai.recipes.recipe_search constructors above."
    )


def run_recipe_search_tests(queries: List[str], top_k: int) -> None:
    print("\n=== EMBEDDING / RECIPE SEARCH TESTS ===")

    try:
        recipe_search = make_recipe_search()
    except Exception as exc:
        print(f"[ERROR] Cannot create recipe_search: {exc}")
        inspect_recipe_search_module()
        return

    print(f"RecipeSearch object: {recipe_search.__class__}")

    for query in queries:
        print(f"\n--- query: {query!r} ---")

        try:
            raw = recipe_search.search(query, top_k=top_k)
        except TypeError:
            raw = recipe_search.search(query)
        except Exception as exc:
            print(f"[ERROR] search failed: {exc}")
            continue

        if isinstance(raw, dict):
            if "recipes" in raw and isinstance(raw["recipes"], list):
                raw = raw["recipes"]
            else:
                raw = list(raw.values())

        if not isinstance(raw, list):
            print(f"[ERROR] search returned non-list: {type(raw)}")
            continue

        normalized = [r for r in raw if isinstance(r, dict)]
        print_recipe_list(f"RecipeSearch top {top_k} for {query!r}", normalized, top_k)


def run_lexical_baseline(recipes: List[Dict[str, Any]], queries: List[str], top_k: int) -> None:
    print("\n=== LEXICAL BASELINE TESTS ===")
    print("Это не embeddings. Это простой baseline: есть ли вообще рецепты с такими словами.")

    for query in queries:
        found = lexical_search(recipes, query, top_k=top_k)
        print_recipe_list(f"Lexical top {top_k} for {query!r}", found, top_k)


def run_meal_planner_candidate_debug(top_k: int) -> None:
    print("\n=== MEALPLANNER CANDIDATE DEBUG ===")

    try:
        from ai.llm.nutrition_engine import NutritionEngine
        from ai.core.meal_planner import MealPlanner
        from ai.core.user_profile import UserProfile
        from ai.core.decision.portion_optimizer import PortionOptimizer
        from ai.core.decision.safety_checker import SafetyChecker
        from ai.core.decision.preference_scorer import PreferenceScorer
        from ai.core.decision.diversity_engine import DiversityEngine
    except Exception as exc:
        print(f"[ERROR] cannot import planner modules: {exc}")
        return

    try:
        recipe_search = make_recipe_search()
    except Exception as exc:
        print(f"[ERROR] cannot create actual RecipeSearch: {exc}")
        return

    profile = UserProfile(
        goal="balanced",
        target_calories=2000,
        meals_per_day=3,
        activity_level="moderate",
        age=25,
        sex="male",
        height_cm=185,
        weight_kg=70,
        preferred_ingredients=[],
        disliked_ingredients=[],
        excluded_ingredients=[],
        allergies=[],
    )

    engine = NutritionEngine()
    optimizer = PortionOptimizer(engine)

    planner = MealPlanner(
        recipe_search=recipe_search,
        nutrition_engine=engine,
        safety_checker=SafetyChecker(),
        preference_scorer=PreferenceScorer(),
        diversity_engine=DiversityEngine(),
        substitution_engine=None,
        portion_optimizer=optimizer,
        llm=None,
    )

    candidates = planner._fetch_candidates(profile, top_k)

    print_recipe_list("MealPlanner _fetch_candidates", candidates, top_k=top_k)

    rice_count = 0
    for recipe in candidates:
        if "rice" in ingredient_names(recipe.get("ingredients", [])):
            rice_count += 1

    print(f"\nrice in candidates: {rice_count}/{len(candidates)}")

    if candidates:
        print("\nFirst candidate raw:")
        pprint(candidates[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topk", type=int, default=15)
    parser.add_argument("--queries", nargs="*", default=DEFAULT_QUERIES)
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--skip-planner", action="store_true")
    args = parser.parse_args()

    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"RECIPES_JSON: {RECIPES_JSON}")

    recipes = load_recipes()
    analyze_dataset(recipes)

    run_lexical_baseline(recipes, args.queries, args.topk)

    if not args.skip_search:
        run_recipe_search_tests(args.queries, args.topk)

    if not args.skip_planner:
        run_meal_planner_candidate_debug(args.topk)


if __name__ == "__main__":
    main()
