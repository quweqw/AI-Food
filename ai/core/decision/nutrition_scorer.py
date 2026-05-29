from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Union


logger = logging.getLogger("NutritionScorer")
Ingredient = Union[str, Dict[str, Any]]


class NutritionScorer:
    """
    Нутриентная оценка продукта/блюда.

    ВАЖНО:
    - Это НЕ vision scorer для YOLO/CLIP.
    - Этот класс оценивает качество питания: protein density, fat density,
      carbs density, health_score, satiety_density.
    - Поддерживает новый формат ингредиентов:
      {"name": "rice", "grams": 180, "state": "cooked"}.
    """

    def __init__(self, nutrition_engine):
        self.engine = nutrition_engine

    # ==========================
    # PUBLIC
    # ==========================

    def score(
        self,
        name: str,
        grams: float = 100.0,
        state: Optional[str] = None,
        profile: Optional[Union[dict, Any]] = None,
        meal_type: str = "lunch",
    ) -> dict:
        """
        Оценка одного ингредиента.

        Возвращает значения 0..1:
        - health_score
        - satiety_density
        - protein_density
        - fat_density
        - carbs_density
        """

        if not name:
            return self._empty()

        try:
            data = self._calculate_single(
                name=name,
                grams=grams,
                state=state,
                profile=profile,
                meal_type=meal_type,
            )
        except Exception as exc:
            logger.warning(f"NutritionScorer error for {name}: {exc}")
            return self._empty()

        return self._score_from_nutrition(data)

    def score_ingredient(
        self,
        ingredient: Ingredient,
        profile: Optional[Union[dict, Any]] = None,
        meal_type: str = "lunch",
    ) -> dict:
        """
        Оценка одного ингредиента в формате str или dict.
        """

        parsed = self._parse_ingredient(ingredient)

        return self.score(
            name=parsed["name"],
            grams=parsed["grams"],
            state=parsed["state"],
            profile=profile,
            meal_type=meal_type,
        )

    def score_meal(
        self,
        ingredients: List[Ingredient],
        profile: Optional[Union[dict, Any]] = None,
        meal_type: str = "lunch",
    ) -> dict:
        """
        Оценка блюда.

        ВАЖНО:
        Итог считается взвешенно по калориям, чтобы 5 г масла
        не влияло на оценку так же, как 200 г курицы/риса.
        """

        if not ingredients:
            return self._empty_meal()

        item_scores = []
        total_calories = 0.0

        for ing in ingredients:
            parsed = self._parse_ingredient(ing)

            if not parsed["name"]:
                continue

            try:
                nutrition = self._calculate_single(
                    name=parsed["name"],
                    grams=parsed["grams"],
                    state=parsed["state"],
                    profile=profile,
                    meal_type=meal_type,
                )
            except Exception as exc:
                logger.warning(f"NutritionScorer meal item error for {parsed['name']}: {exc}")
                continue

            score = self._score_from_nutrition(nutrition)
            calories = float(nutrition.get("calories", 0.0) or 0.0)

            if calories <= 0:
                continue

            item_scores.append({
                "name": parsed["name"],
                "calories": calories,
                "score": score,
            })
            total_calories += calories

        if not item_scores or total_calories <= 0:
            return self._empty_meal()

        keys = [
            "health_score",
            "protein_density",
            "fat_density",
            "carbs_density",
            "satiety_density",
            "fiber_score",
            "sugar_penalty",
            "sodium_penalty",
            "saturated_fat_penalty",
            "energy_density_penalty",
        ]

        weighted = {}
        for key in keys:
            weighted[key] = sum(
                item["score"].get(key, 0.0) * item["calories"]
                for item in item_scores
            ) / total_calories

        return {
            **{k: round(self._clamp(v), 3) for k, v in weighted.items()},
            "items_count": len(item_scores),
            "total_calories": round(total_calories, 1),
            "items": item_scores,
        }

    # ==========================
    # INTERNAL SCORE
    # ==========================

    def _score_from_nutrition(self, data: dict) -> dict:
        if not data:
            return self._empty()

        calories = self._safe_float(data.get("calories", 0.0))
        protein = self._safe_float(data.get("protein", 0.0))
        fat = self._safe_float(data.get("fat", 0.0))
        carbs = self._safe_float(data.get("carbs", 0.0))
        fiber = self._safe_float(data.get("fiber", 0.0))
        sugar = self._safe_float(data.get("sugar", 0.0))
        sodium_mg = self._safe_float(data.get("sodium_mg", 0.0))
        saturated_fat = self._safe_float(data.get("saturated_fat", 0.0))
        eaten_weight_g = self._safe_float(
            data.get("eaten_weight_g", data.get("weight_g", 100.0)),
            100.0,
        )

        if calories <= 0:
            return self._empty()

        protein_density = self._clamp((protein * 4.0) / calories)
        fat_density = self._clamp((fat * 9.0) / calories)
        carbs_density = self._clamp((carbs * 4.0) / calories)

        # Клетчатка на 100 ккал. Хороший уровень: 4-6 г/100 ккал.
        fiber_per_100kcal = fiber / max(calories / 100.0, 1e-6)
        fiber_score = self._clamp(fiber_per_100kcal / 6.0)

        # Сахар как доля калорий. Если >25% калорий из сахара — сильный штраф.
        sugar_energy_share = self._clamp((sugar * 4.0) / calories)
        sugar_penalty = self._clamp(sugar_energy_share / 0.25)

        # Натрий на 100 ккал. 350+ мг/100 ккал — уже ощутимый штраф.
        sodium_per_100kcal = sodium_mg / max(calories / 100.0, 1e-6)
        sodium_penalty = self._clamp(sodium_per_100kcal / 350.0)

        # Насыщенные жиры как доля калорий. 13%+ — высокий уровень.
        sat_fat_energy_share = self._clamp((saturated_fat * 9.0) / calories)
        saturated_fat_penalty = self._clamp(sat_fat_energy_share / 0.13)

        # Энергетическая плотность: ккал/г.
        # Для обычных блюд 1-2 ккал/г нормально; 4+ — плотная еда.
        energy_density = calories / max(eaten_weight_g, 1.0)
        energy_density_penalty = self._clamp((energy_density - 1.0) / 3.0)

        # Жир не всегда плохой, поэтому штрафуем главным образом избыточный жир.
        fat_excess_penalty = self._clamp((fat_density - 0.35) / 0.35)

        health_score = (
            0.38 * protein_density
            + 0.20 * fiber_score
            + 0.14 * (1.0 - fat_excess_penalty)
            + 0.10 * (1.0 - sugar_penalty)
            + 0.08 * (1.0 - sodium_penalty)
            + 0.06 * (1.0 - saturated_fat_penalty)
            + 0.04 * (1.0 - energy_density_penalty)
        )

        health_score = self._clamp(health_score)

        satiety_density = (
            0.48 * protein_density
            + 0.32 * fiber_score
            + 0.20 * (1.0 - energy_density_penalty)
        )

        satiety_density = self._clamp(satiety_density)

        return {
            "health_score": round(health_score, 3),
            "protein_density": round(protein_density, 3),
            "fat_density": round(fat_density, 3),
            "carbs_density": round(carbs_density, 3),
            "satiety_density": round(satiety_density, 3),
            "fiber_score": round(fiber_score, 3),
            "sugar_penalty": round(sugar_penalty, 3),
            "sodium_penalty": round(sodium_penalty, 3),
            "saturated_fat_penalty": round(saturated_fat_penalty, 3),
            "energy_density_penalty": round(energy_density_penalty, 3),
        }

    # ==========================
    # NUTRITION ENGINE COMPAT
    # ==========================

    def _calculate_single(
        self,
        name: str,
        grams: float,
        state: Optional[str],
        profile: Optional[Union[dict, Any]],
        meal_type: str,
    ) -> dict:
        """
        Поддерживает и новый NutritionEngine, и старую версию calculate_single.
        """

        name = self._normalize_name(name)
        grams = self._safe_float(grams, 100.0)

        # Новый NutritionEngine: calculate_single(name, grams, state=..., profile=..., meal_type=...)
        try:
            return self.engine.calculate_single(
                name=name,
                grams=grams,
                state=state,
                profile=profile,
                meal_type=meal_type,
            )
        except TypeError:
            pass

        # Предыдущая версия: calculate_single(name, grams, profile=..., meal_type=...)
        try:
            return self.engine.calculate_single(
                name=name,
                grams=grams,
                profile=profile,
                meal_type=meal_type,
            )
        except TypeError:
            pass

        # Старая версия: calculate_single(name, grams)
        try:
            return self.engine.calculate_single(name, grams)
        except TypeError:
            pass

        # Абсолютный fallback через calculate()
        ingredient = {"name": name, "grams": grams}
        if state:
            ingredient["state"] = state

        try:
            return self.engine.calculate(
                [ingredient],
                profile=profile,
                meal_type=meal_type,
            )
        except TypeError:
            return self.engine.calculate([ingredient])

    # ==========================
    # PARSING / HELPERS
    # ==========================

    def _parse_ingredient(self, ingredient: Ingredient) -> dict:
        if isinstance(ingredient, str):
            return {
                "name": self._normalize_name(ingredient),
                "grams": 100.0,
                "state": None,
            }

        if not isinstance(ingredient, dict):
            return {
                "name": "",
                "grams": 100.0,
                "state": None,
            }

        grams = ingredient.get("grams")
        if grams is None:
            grams = ingredient.get("amount")
        if grams is None:
            grams = ingredient.get("weight_g")
        if grams is None:
            grams = 100.0

        state = ingredient.get("state") or ingredient.get("input_state")

        return {
            "name": self._normalize_name(ingredient.get("name", "")),
            "grams": self._safe_float(grams, 100.0),
            "state": self._normalize_state(state),
        }

    def _normalize_name(self, value: Any) -> str:
        value = str(value or "").strip().lower()
        value = value.replace("-", "_")
        value = "_".join(value.split())
        return value

    def _normalize_state(self, value: Any) -> Optional[str]:
        if not value:
            return None

        value = str(value).strip().lower()

        aliases = {
            "raw": "raw",
            "dry": "raw",
            "uncooked": "raw",
            "сырой": "raw",
            "сырая": "raw",

            "cooked": "cooked",
            "prepared": "cooked",
            "готовый": "cooked",
            "готовое": "cooked",
            "вареный": "cooked",
            "варёный": "cooked",
        }

        return aliases.get(value)

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    def _clamp(self, value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    def _empty(self) -> dict:
        return {
            "health_score": 0.0,
            "protein_density": 0.0,
            "fat_density": 0.0,
            "carbs_density": 0.0,
            "satiety_density": 0.0,
            "fiber_score": 0.0,
            "sugar_penalty": 0.0,
            "sodium_penalty": 0.0,
            "saturated_fat_penalty": 0.0,
            "energy_density_penalty": 0.0,
        }

    def _empty_meal(self) -> dict:
        return {
            **self._empty(),
            "items_count": 0,
            "total_calories": 0.0,
            "items": [],
        }
