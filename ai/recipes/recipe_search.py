from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import faiss
import numpy as np
import open_clip
import torch

from ai.recipes.recipe_rules import RecipeSearchRules


logger = logging.getLogger("RecipeSearch")

MODULE_DIR = Path(__file__).resolve().parent          # AI Food/ai/recipes
AI_DIR = MODULE_DIR.parent                            # AI Food/ai
PROJECT_ROOT = AI_DIR.parent                          # AI Food
DEFAULT_DATA_DIR = AI_DIR / "data"


class RecipeSearch:
    """
    Поиск рецептов через CLIP text embeddings + prod rerank.

    Что делает:
    1. Ищет кандидатов через FAISS.
    2. Нормализует ингредиенты через food_aliases.json.
    3. Использует food_groups.json для понимания структуры блюда.
    4. Использует recipe_search_rules.json для stop-words, dessert-words, весов и штрафов.
    5. Возвращает уже rerank-нутые рецепты.
    """

    def __init__(
        self,
        recipes_path: Optional[Union[str, Path]] = None,
        index_path: Optional[Union[str, Path]] = None,
        embeddings_path: Optional[Union[str, Path]] = None,
        data_dir: Optional[Union[str, Path]] = None,
        model_name: str = "ViT-L-14",
        pretrained: str = "openai",
        device: Optional[str] = None,
    ):
        self.module_dir = MODULE_DIR
        self.ai_dir = AI_DIR
        self.project_root = PROJECT_ROOT
        self.data_dir = self._resolve_data_dir(data_dir)

        self.model_name = model_name
        self.pretrained = pretrained
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.recipes_path = Path(recipes_path) if recipes_path else MODULE_DIR / "recipes.json"
        self.index_path = Path(index_path) if index_path else MODULE_DIR / "recipe_index.faiss"
        self.embeddings_path = Path(embeddings_path) if embeddings_path else MODULE_DIR / "recipe_embeddings.npy"

        self.rules = RecipeSearchRules(data_dir=self.data_dir)

        self.aliases = self._load_optional_json("food_aliases.json")
        self.food_groups = self._load_optional_json("food_groups.json")

        self.recipes = self._load_recipes(self.recipes_path)
        self.index = self._load_index(self.index_path)
        self.embeddings = self._load_embeddings(self.embeddings_path)

        self.model = None
        self.tokenizer = None

        self._validate_index_alignment()

    # ──────────────────────────────────────────────
    # LOAD
    # ──────────────────────────────────────────────

    def _resolve_data_dir(self, data_dir: Optional[Union[str, Path]]) -> Path:
        if data_dir is not None:
            path = Path(data_dir).resolve()
            if path.exists():
                return path

        candidates = [
            DEFAULT_DATA_DIR,              # AI Food/ai/data
            PROJECT_ROOT / "data",         # AI Food/data fallback
            MODULE_DIR,                    # AI Food/ai/recipes fallback
        ]

        for path in candidates:
            if path.exists():
                return path

        return DEFAULT_DATA_DIR

    def _load_optional_json(self, filename: str) -> dict:
        candidates = [
            self.data_dir / filename,
            DEFAULT_DATA_DIR / filename,
            PROJECT_ROOT / "data" / filename,
            MODULE_DIR / filename,
        ]

        for path in candidates:
            if not path.exists():
                continue

            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    logger.warning("%s must contain JSON object: %s", filename, path)
                    return {}

                logger.info("Loaded %s from %s", filename, path)
                return data

            except Exception as e:
                logger.warning("Failed to load %s from %s: %s", filename, path, e)
                return {}

        logger.warning("%s not found. Tried: %s", filename, " | ".join(str(p) for p in candidates))
        return {}

    def _load_recipes(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"recipes.json not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(f"recipes.json must contain list, got: {type(data)}")

        recipes = []
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                logger.warning("Skip invalid recipe at index %s: not dict", idx)
                continue
            recipes.append(item)

        if not recipes:
            raise ValueError(f"No valid recipes found in {path}")

        return recipes

    def _load_index(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(
                f"recipe_index.faiss not found: {path}. "
                f"Run: python -m ai.recipes.build_index"
            )
        return faiss.read_index(str(path))

    def _load_embeddings(self, path: Path) -> np.ndarray:
        if not path.exists():
            raise FileNotFoundError(
                f"recipe_embeddings.npy not found: {path}. "
                f"Run: python -m ai.recipes.build_index"
            )
        return np.load(path)

    def _validate_index_alignment(self) -> None:
        recipe_count = len(self.recipes)

        if self.embeddings.shape[0] != recipe_count:
            logger.warning(
                "Embeddings count mismatch: embeddings=%s recipes=%s. "
                "Run: python -m ai.recipes.build_index",
                self.embeddings.shape[0],
                recipe_count,
            )

        if self.index.ntotal != recipe_count:
            logger.warning(
                "FAISS index count mismatch: index=%s recipes=%s. "
                "Run: python -m ai.recipes.build_index",
                self.index.ntotal,
                recipe_count,
            )

    # ──────────────────────────────────────────────
    # MODEL
    # ──────────────────────────────────────────────

    def _ensure_model_loaded(self) -> None:
        if self.model is not None and self.tokenizer is not None:
            return

        logger.info(
            "Loading CLIP text model: %s / %s on %s",
            self.model_name,
            self.pretrained,
            self.device,
        )

        model, _, _ = open_clip.create_model_and_transforms(
            self.model_name,
            pretrained=self.pretrained,
        )

        self.model = model.to(self.device)
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(self.model_name)

    def encode_query(self, text: str) -> np.ndarray:
        self._ensure_model_loaded()

        query = str(text or "").strip()
        if not query:
            query = "balanced meal"

        with torch.no_grad():
            tokens = self.tokenizer([query]).to(self.device)
            emb = self.model.encode_text(tokens)
            emb = emb.cpu().numpy()

        emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-10)
        return emb.astype("float32")

    # ──────────────────────────────────────────────
    # PUBLIC SEARCH
    # ──────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 10,
        candidate_pool: Optional[int] = None,
        rerank: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список рецептов.

        score:
            итоговый score после rerank.

        retrieval_score:
            исходный FAISS / CLIP score.

        rerank_score:
            score после логики правил.
        """

        top_k = max(1, int(top_k))
        query = str(query or "").strip()

        if not query:
            query = "balanced meal"

        emb = self.encode_query(query)

        if candidate_pool is None:
            search_k = max(top_k * 10, 50)
        else:
            search_k = int(candidate_pool)

        search_k = max(top_k, min(search_k, len(self.recipes), self.index.ntotal))

        distances, indices = self.index.search(emb, search_k)

        candidates: List[Dict[str, Any]] = []

        for retrieval_score, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.recipes):
                continue

            raw_recipe = self.recipes[int(idx)]
            recipe = self._normalize_recipe(raw_recipe)

            if recipe is None:
                continue

            recipe["retrieval_score"] = float(retrieval_score)

            if rerank:
                reranked = self._rerank_one(recipe, query)
                recipe["rerank_score"] = reranked["score"]
                recipe["rerank_components"] = reranked["components"]
                recipe["score"] = reranked["score"]
            else:
                recipe["rerank_score"] = float(retrieval_score)
                recipe["rerank_components"] = {}
                recipe["score"] = float(retrieval_score)

            candidates.append(recipe)

        candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        return [
            self._export_recipe(item)
            for item in candidates[:top_k]
        ]

    # ──────────────────────────────────────────────
    # NORMALIZATION
    # ──────────────────────────────────────────────

    def _normalize_recipe(self, recipe: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        name = recipe.get("name") or recipe.get("title") or recipe.get("dish_name")
        if not name:
            return None

        raw_ingredients = recipe.get("ingredients", [])
        ingredients = []

        if isinstance(raw_ingredients, list):
            for item in raw_ingredients:
                if isinstance(item, str):
                    raw_name = item
                elif isinstance(item, dict):
                    raw_name = item.get("name") or item.get("ingredient") or ""
                else:
                    raw_name = ""

                normalized = self._normalize_ingredient_name(raw_name)
                if normalized:
                    ingredients.append(normalized)

        ingredients = self._dedupe_keep_order(ingredients)

        return {
            "name": str(name),
            "ingredients": ingredients,
            "instructions": recipe.get("instructions", recipe.get("steps", [])),
            "tags": recipe.get("tags", []),
            "cuisine": recipe.get("cuisine"),
            "servings": recipe.get("servings", 1),
            "nutrition": recipe.get("nutrition"),
            "source": recipe,
        }

    def _normalize_ingredient_name(self, name: str) -> str:
        if not name:
            return ""

        text = str(name).lower().strip()
        text = text.replace("-", " ")
        text = text.replace("_", " ")

        text = re.sub(r"\([^)]*\)", " ", text)

        for phrase in getattr(self.rules, "noise_phrases", []):
            text = text.replace(phrase, " ")

        text = re.sub(r"[^a-zа-яё0-9\s]+", " ", text, flags=re.IGNORECASE)
        text = " ".join(text.split())

        if not text:
            return ""

        underscored = text.replace(" ", "_")

        result = (
            self.aliases.get(text)
            or self.aliases.get(underscored)
            or underscored
        )

        result = str(result).lower().strip().replace(" ", "_")
        return result

    def _normalize_text_key(self, text: str) -> str:
        return self._normalize_ingredient_name(text)

    def _dedupe_keep_order(self, items: List[str]) -> List[str]:
        result = []
        seen = set()

        for item in items:
            if not item:
                continue
            if item in seen:
                continue

            result.append(item)
            seen.add(item)

        return result

    # ──────────────────────────────────────────────
    # QUERY TERMS
    # ──────────────────────────────────────────────

    def _tokenize_query_food_terms(self, query: str) -> set[str]:
        text = str(query or "").lower().strip()
        text = text.replace("-", " ").replace("_", " ")
        text = re.sub(r"[^a-zа-яё0-9\s]+", " ", text, flags=re.IGNORECASE)
        tokens = [t for t in text.split() if t]

        terms = set()

        # 3-grams, 2-grams, 1-grams
        for n in (3, 2, 1):
            for i in range(0, max(0, len(tokens) - n + 1)):
                phrase = " ".join(tokens[i:i + n])
                norm = self._normalize_text_key(phrase)

                if not norm:
                    continue

                if norm in self.rules.goal_words:
                    continue

                if norm in self.rules.stop_ingredients:
                    continue

                if len(norm) <= 1:
                    continue

                terms.add(norm)

        # Убираем части, если есть более длинная форма.
        # Например: ground_beef оставляем, beef можно оставить тоже,
        # потому что aliases могут привести оба к beef.
        return terms

    def _is_generic_query(self, query: str, query_terms: set[str]) -> bool:
        if query_terms:
            return False

        lowered = str(query or "").lower()
        goal_hits = sum(1 for w in self.rules.goal_words if w in lowered)
        return goal_hits > 0 or not lowered.strip()

    # ──────────────────────────────────────────────
    # RERANK
    # ──────────────────────────────────────────────

    def _rerank_one(self, recipe: Dict[str, Any], query: str) -> Dict[str, Any]:
        retrieval = self._clamp(float(recipe.get("retrieval_score", 0.0)))

        query_terms = self._tokenize_query_food_terms(query)
        generic_query = self._is_generic_query(query, query_terms)

        recipe_ingredients = set(recipe.get("ingredients", []))
        key_ingredients = set(self._key_ingredients(recipe.get("ingredients", [])))

        ingredient_match = self._ingredient_match_score(
            query_terms=query_terms,
            recipe_ingredients=recipe_ingredients,
            key_ingredients=key_ingredients,
        )

        name_match = self._name_match_score(recipe.get("name", ""), query_terms)
        meal_structure = self._meal_structure_score(recipe)
        db_coverage = self._db_coverage_score(recipe.get("ingredients", []))

        dessert_penalty = self._dessert_penalty(recipe, query)
        missing_food_penalty = 0.0

        if query_terms and ingredient_match <= 0:
            missing_food_penalty = self.rules.penalty("missing_food_penalty", 0.18)

        weak_meal_penalty = 0.0
        if meal_structure < 0.45:
            weak_meal_penalty = 0.08

        if generic_query:
            # Для запросов типа "balanced", "high protein dinner"
            # нельзя доверять только CLIP, иначе снова будут Pancakes/Pryaniki.
            final = (
                0.18 * retrieval +
                0.47 * meal_structure +
                0.20 * db_coverage +
                0.15 * ingredient_match
                - dessert_penalty
                - weak_meal_penalty
            )
        else:
            final = (
                self.rules.weight("retrieval", 0.45) * retrieval +
                self.rules.weight("ingredient_match", 0.35) * ingredient_match +
                self.rules.weight("name_match", 0.10) * name_match +
                self.rules.weight("meal_structure", 0.10) * meal_structure
                - dessert_penalty
                - missing_food_penalty
                - weak_meal_penalty
            )

        final = self._clamp(final)

        return {
            "score": final,
            "components": {
                "retrieval": round(retrieval, 3),
                "ingredient_match": round(ingredient_match, 3),
                "name_match": round(name_match, 3),
                "meal_structure": round(meal_structure, 3),
                "db_coverage": round(db_coverage, 3),
                "dessert_penalty": round(dessert_penalty, 3),
                "missing_food_penalty": round(missing_food_penalty, 3),
                "weak_meal_penalty": round(weak_meal_penalty, 3),
                "generic_query": generic_query,
                "query_terms": sorted(query_terms),
            },
        }

    def _key_ingredients(self, ingredients: List[str]) -> List[str]:
        result = []

        for ing in ingredients:
            norm = self._normalize_ingredient_name(ing)

            if not norm:
                continue

            if norm in self.rules.stop_ingredients:
                continue

            result.append(norm)

        return self._dedupe_keep_order(result)

    def _ingredient_match_score(
        self,
        query_terms: set[str],
        recipe_ingredients: set[str],
        key_ingredients: set[str],
    ) -> float:
        if not query_terms:
            return 0.5

        matched = 0.0

        for term in query_terms:
            if term in recipe_ingredients or term in key_ingredients:
                matched += 1.0
                continue

            term_category = self._category(term)
            if term_category != "unknown":
                recipe_categories = {self._category(i) for i in key_ingredients}
                if term_category in recipe_categories:
                    matched += 0.45

        return self._clamp(matched / max(len(query_terms), 1))

    def _name_match_score(self, name: str, query_terms: set[str]) -> float:
        if not query_terms:
            return 0.0

        normalized_name = self._normalize_name_for_match(name)

        matched = 0
        for term in query_terms:
            if term in normalized_name:
                matched += 1

        return self._clamp(matched / max(len(query_terms), 1))

    def _normalize_name_for_match(self, name: str) -> str:
        text = str(name or "").lower()
        text = text.replace("-", " ").replace("_", " ")
        text = re.sub(r"[^a-zа-яё0-9\s]+", " ", text, flags=re.IGNORECASE)
        return "_".join(text.split())

    def _meal_structure_score(self, recipe: Dict[str, Any]) -> float:
        ingredients = self._key_ingredients(recipe.get("ingredients", []))

        if not ingredients:
            return 0.0

        categories = {self._category(i) for i in ingredients}

        has_protein = "protein" in categories
        has_carbs = "carbs" in categories
        has_vegetable = "vegetable" in categories
        has_fat = "fat" in categories

        score = 0.0

        if has_protein:
            score += 0.42

        if has_carbs:
            score += 0.25

        if has_vegetable:
            score += 0.23

        if has_fat:
            score += 0.05

        if not self._is_dessert_like(recipe):
            score += 0.05

        return self._clamp(score)

    def _db_coverage_score(self, ingredients: List[str]) -> float:
        key_ingredients = self._key_ingredients(ingredients)

        if not key_ingredients:
            return 0.0

        covered = 0

        for ing in key_ingredients:
            if self._group_info(ing):
                covered += 1

        return self._clamp(covered / max(len(key_ingredients), 1))

    def _dessert_penalty(self, recipe: Dict[str, Any], query: str) -> float:
        if not self._is_dessert_like(recipe):
            return 0.0

        lowered_query = str(query or "").lower()

        if any(x in lowered_query for x in self.rules.dessert_context_words):
            return self.rules.penalty("dessert_penalty_strict", 0.25)

        return self.rules.penalty("dessert_penalty_soft", 0.08)

    def _is_dessert_like(self, recipe: Dict[str, Any]) -> bool:
        name = self._normalize_name_for_match(recipe.get("name", ""))

        if name in self.rules.dessert_words:
            return True

        name_tokens = set(name.split("_"))
        if name_tokens & self.rules.dessert_words:
            return True

        tags = recipe.get("tags", [])
        if isinstance(tags, list):
            normalized_tags = {
                self._normalize_name_for_match(str(t))
                for t in tags
            }

            for tag in normalized_tags:
                if tag in self.rules.dessert_words:
                    return True
                if set(tag.split("_")) & self.rules.dessert_words:
                    return True

        return False

    # ──────────────────────────────────────────────
    # FOOD GROUPS
    # ──────────────────────────────────────────────

    def _group_info(self, ingredient: str) -> dict:
        name = self._normalize_ingredient_name(ingredient)

        if name in self.food_groups:
            return self.food_groups[name]

        alias = self.aliases.get(name)
        if alias and alias in self.food_groups:
            return self.food_groups[alias]

        return {}

    def _category(self, ingredient: str) -> str:
        info = self._group_info(ingredient)
        category = info.get("category", "unknown")
        return str(category or "unknown").lower()

    # ──────────────────────────────────────────────
    # EXPORT
    # ──────────────────────────────────────────────

    def _export_recipe(self, recipe: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": recipe.get("name", "unknown meal"),
            "ingredients": recipe.get("ingredients", []),
            "instructions": recipe.get("instructions", []),
            "tags": recipe.get("tags", []),
            "cuisine": recipe.get("cuisine"),
            "servings": recipe.get("servings", 1),
            "nutrition": recipe.get("nutrition"),
            "score": float(recipe.get("score", 0.0)),
            "retrieval_score": float(recipe.get("retrieval_score", 0.0)),
            "rerank_score": float(recipe.get("rerank_score", 0.0)),
            "rerank_components": recipe.get("rerank_components", {}),
            "source": recipe.get("source", {}),
        }

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def _clamp(self, value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, float(value)))