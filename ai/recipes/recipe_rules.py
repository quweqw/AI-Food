from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional, Union


logger = logging.getLogger("RecipeSearchRules")

MODULE_DIR = Path(__file__).resolve().parent
AI_DIR = MODULE_DIR.parent
PROJECT_ROOT = AI_DIR.parent
DEFAULT_DATA_DIR = AI_DIR / "data"


class RecipeSearchRules:
    """
    Единый загрузчик правил для:
    - recipe_search.py
    - build_index.py

    Важно:
    все доменные списки хранятся в ai/data/recipe_search_rules.json,
    а не в коде.
    """

    def __init__(self, data_dir: Optional[Union[str, Path]] = None):
        self.data_dir = self._resolve_data_dir(data_dir)
        self.raw = self._load_required("recipe_search_rules.json")

        normalization = self.raw.get("normalization", {})
        ingredients = self.raw.get("ingredients", {})
        query = self.raw.get("query", {})
        recipe_types = self.raw.get("recipe_types", {})
        indexing = self.raw.get("indexing", {})
        rerank = self.raw.get("rerank", {})

        self.noise_phrases = self._as_list(
            normalization.get("noise_phrases", [])
        )

        self.stop_ingredients = set(
            self._as_list(ingredients.get("stop_ingredients", []))
        )

        self.goal_words = set(
            self._as_list(query.get("goal_words", []))
        )

        self.dessert_words = set(
            self._as_list(recipe_types.get("dessert_words", []))
        )

        self.dessert_context_words = set(
            self._as_list(recipe_types.get("dessert_context_words", []))
        )

        self.max_key_ingredients = self._as_int(
            indexing.get("max_key_ingredients", 28),
            default=28,
        )

        self.max_all_ingredients = self._as_int(
            indexing.get("max_all_ingredients", 40),
            default=40,
        )

        self.max_tags = self._as_int(
            indexing.get("max_tags", 10),
            default=10,
        )

        self.rerank_weights = rerank.get("weights", {}) or {}
        self.rerank_penalties = rerank.get("penalties", {}) or {}

        self._validate()

    def _resolve_data_dir(self, data_dir: Optional[Union[str, Path]]) -> Path:
        if data_dir is not None:
            path = Path(data_dir).resolve()
            if path.exists():
                return path

        candidates = [
            DEFAULT_DATA_DIR,
            PROJECT_ROOT / "data",
            MODULE_DIR
        ]

        for path in candidates:
            if path.exists():
                return path

        return DEFAULT_DATA_DIR

    def _load_required(self, filename: str) -> dict:
        path = self.data_dir / filename

        if not path.exists():
            raise FileNotFoundError(
                f"{filename} not found: {path}"
            )

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(
                f"{filename} must contain JSON object at top level"
            )

        logger.info("Loaded %s from %s", filename, path)
        return data

    def _as_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []

        result = []

        for item in value:
            text = str(item or "").strip().lower()

            if text:
                result.append(text)

        return result

    def _as_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _as_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    def weight(self, key: str, default: float = 0.0) -> float:
        return self._as_float(
            self.rerank_weights.get(key, default),
            default,
        )

    def penalty(self, key: str, default: float = 0.0) -> float:
        return self._as_float(
            self.rerank_penalties.get(key, default),
            default,
        )

    def _validate(self) -> None:
        if not self.stop_ingredients:
            raise ValueError(
                "recipe_search_rules.json: ingredients.stop_ingredients is empty"
            )

        if not self.goal_words:
            raise ValueError(
                "recipe_search_rules.json: query.goal_words is empty"
            )

        if not self.dessert_words:
            raise ValueError(
                "recipe_search_rules.json: recipe_types.dessert_words is empty"
            )

        required_weights = {
            "retrieval",
            "ingredient_match",
            "name_match",
            "meal_structure"
        }

        missing_weights = [
            key for key in required_weights
            if key not in self.rerank_weights
        ]

        if missing_weights:
            raise ValueError(
                f"recipe_search_rules.json: missing rerank weights: {missing_weights}"
            )