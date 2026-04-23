from __future__ import annotations

from copy import deepcopy
from math import exp
from typing import Any, Dict, List, Optional


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class MealPlanner:
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
    ):
        self.recipe_search = recipe_search
        self.nutrition_engine = nutrition_engine
        self.llm = llm
        self.safety_checker = safety_checker
        self.preference_scorer = preference_scorer
        self.diversity_engine = diversity_engine
        self.substitution_engine = substitution_engine
        self.ranking_engine = ranking_engine

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
        meals_per_day = self._clamp_meals_per_day(getattr(user_profile, "meals_per_day", 3))

        target_calories = self._get_target_calories(user_profile, goal)
        macro_targets = self._get_macro_targets(target_calories, goal)

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

        for day_idx in range(days):
            day_result = self._build_day(
                day_number=day_idx + 1,
                user_profile=simulated_profile,
                candidates=candidates,
                target_calories=target_calories,
                macro_targets=macro_targets,
                meals_per_day=meals_per_day,
            )
            full_plan.append(day_result)

            for meal in day_result["meals"]:
                simulated_profile.add_meal(meal["ingredients"])

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
            return int(tdee - 450)
        if goal == "muscle_gain":
            return int(tdee + 300)
        return int(tdee)

    def _get_macro_targets(self, calories: int, goal: str) -> Dict[str, float]:
        if goal == "weight_loss":
            ratios = {"protein": 0.35, "fat": 0.25, "carbs": 0.40}
        elif goal == "muscle_gain":
            ratios = {"protein": 0.30, "fat": 0.25, "carbs": 0.45}
        else:
            ratios = {"protein": 0.28, "fat": 0.28, "carbs": 0.44}

        return {
            "protein_g": round((calories * ratios["protein"]) / 4, 1),
            "fat_g": round((calories * ratios["fat"]) / 9, 1),
            "carbs_g": round((calories * ratios["carbs"]) / 4, 1),
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

    # ==============================
    # CANDIDATES
    # ==============================

    def _build_search_query(self, user_profile) -> str:
        parts = []

        goal = self._normalize_goal(getattr(user_profile, "goal", "balanced"))
        parts.append(goal)

        if getattr(user_profile, "preferred_ingredients", None):
            parts.extend(user_profile.preferred_ingredients[:3])

        if getattr(user_profile, "disliked_ingredients", None):
            parts.extend(user_profile.disliked_ingredients[:2])

        if getattr(user_profile, "excluded_ingredients", None):
            parts.extend(user_profile.excluded_ingredients[:2])

        return " ".join([str(p) for p in parts if p])

    def _fetch_candidates(self, user_profile, candidate_limit: int) -> List[Dict[str, Any]]:
        query = self._build_search_query(user_profile)

        try:
            raw = self.recipe_search.search(query, top_k=candidate_limit)
        except TypeError:
            raw = self.recipe_search.search(query)
        except Exception:
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

        return candidates

    def _normalize_recipe(self, recipe: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(recipe, dict):
            return None

        ingredients = recipe.get("ingredients", [])
        normalized_ingredients: List[str] = []

        for item in ingredients:
            if isinstance(item, str):
                normalized_ingredients.append(item.strip().lower())
            elif isinstance(item, dict) and item.get("name"):
                normalized_ingredients.append(str(item["name"]).strip().lower())

        name = recipe.get("name") or recipe.get("title") or recipe.get("dish_name") or "unknown meal"

        return {
            "name": str(name),
            "ingredients": normalized_ingredients,
            "instructions": recipe.get("instructions", recipe.get("steps", [])),
            "tags": recipe.get("tags", []),
            "cuisine": recipe.get("cuisine"),
            "score": float(recipe.get("score", 0.5)) if recipe.get("score") is not None else 0.5,
            "source": recipe,
        }

    def _recipe_signature(self, ingredients: List[str]) -> str:
        return "|".join(sorted({i.strip().lower() for i in ingredients if i}))

    def _recipe_nutrition(self, recipe: Dict[str, Any]) -> Dict[str, float]:
        nutrition = recipe.get("nutrition")

        if isinstance(nutrition, dict) and nutrition.get("calories") is not None:
            return {
                "calories": float(nutrition.get("calories", 0)),
                "protein": float(nutrition.get("protein", 0)),
                "fat": float(nutrition.get("fat", 0)),
                "carbs": float(nutrition.get("carbs", 0)),
            }

        ingredients = recipe.get("ingredients", [])
        base = self.nutrition_engine.calculate(ingredients)

        servings = recipe.get("servings", 1)
        try:
            servings = max(1.0, float(servings))
        except Exception:
            servings = 1.0

        return {
            "calories": float(base.get("calories", 0)) / servings,
            "protein": float(base.get("protein", 0)) / servings,
            "fat": float(base.get("fat", 0)) / servings,
            "carbs": float(base.get("carbs", 0)) / servings,
        }

    # ==============================
    # SCORING
    # ==============================

    def _calorie_fit_score(self, actual: float, target: float) -> float:
        if actual <= 0 or target <= 0:
            return 0.0
        ratio = actual / target
        return exp(-((ratio - 1.0) ** 2) / (2 * 0.22 ** 2))

    def _macro_fit_score(self, nutrition: Dict[str, float], target_calories: int, goal: str) -> float:
        calories = max(1.0, float(nutrition.get("calories", 0)))
        protein_ratio = (nutrition.get("protein", 0) * 4) / calories
        fat_ratio = (nutrition.get("fat", 0) * 9) / calories
        carbs_ratio = (nutrition.get("carbs", 0) * 4) / calories

        if goal == "weight_loss":
            targets = {
                "protein": (0.30, 0.48),
                "fat": (0.18, 0.30),
                "carbs": (0.20, 0.42),
            }
        elif goal == "muscle_gain":
            targets = {
                "protein": (0.24, 0.40),
                "fat": (0.18, 0.30),
                "carbs": (0.35, 0.58),
            }
        else:
            targets = {
                "protein": (0.20, 0.35),
                "fat": (0.20, 0.32),
                "carbs": (0.35, 0.55),
            }

        def range_score(value: float, low: float, high: float) -> float:
            if low <= value <= high:
                return 1.0
            if value < low:
                return clamp(1.0 - (low - value) / max(low, 0.01))
            return clamp(1.0 - (value - high) / max(1.0 - high, 0.01))

        p = range_score(protein_ratio, *targets["protein"])
        f = range_score(fat_ratio, *targets["fat"])
        c = range_score(carbs_ratio, *targets["carbs"])

        return (p + f + c) / 3.0

    def _preference_score(self, ingredients: List[str], user_profile) -> float:
        if self.preference_scorer is None:
            return 0.5
        return float(self.preference_scorer.score(ingredients, user_profile))

    def _diversity_score(self, ingredients: List[str], user_profile) -> float:
        if self.diversity_engine is None:
            return 1.0
        return float(self.diversity_engine.score(ingredients, user_profile))

    def _history_penalty(self, ingredients: List[str], user_profile) -> float:
        recent = getattr(user_profile, "recent_meals", []) or []
        if not recent:
            return 0.0

        current = set(i.lower() for i in ingredients)
        penalty = 0.0

        for meal in recent[-5:]:
            past = set(str(i).lower() for i in meal.get("ingredients", []))
            if current == past:
                penalty += 0.65
            overlap = len(current & past)
            penalty += overlap * 0.03

        return penalty

    def _ingredient_penalty(self, ingredients: List[str], user_profile) -> float:
        penalty = 0.0
        disliked = set(i.lower() for i in getattr(user_profile, "disliked_ingredients", []) or [])
        excluded = set(i.lower() for i in getattr(user_profile, "excluded_ingredients", []) or [])

        for ing in ingredients:
            if ing in disliked:
                penalty += 0.12
            if ing in excluded:
                penalty += 0.35

        return penalty

    def _goal_bonus(self, nutrition: Dict[str, float], goal: str) -> float:
        calories = max(1.0, float(nutrition.get("calories", 0)))
        protein_density = (nutrition.get("protein", 0) * 4) / calories
        carbs_density = (nutrition.get("carbs", 0) * 4) / calories

        if goal == "weight_loss":
            return clamp(0.65 * protein_density + 0.20 * (1.0 - carbs_density) + 0.15)
        if goal == "muscle_gain":
            return clamp(0.50 * protein_density + 0.35 * carbs_density + 0.15)
        return clamp(0.40 * protein_density + 0.30 * carbs_density + 0.30)

    def _score_candidate(
        self,
        recipe: Dict[str, Any],
        user_profile,
        target_calories: int,
        goal: str,
        slot_target_calories: float,
    ) -> Dict[str, Any]:
        ingredients = recipe["ingredients"]
        nutrition = self._recipe_nutrition(recipe)

        safety = None
        if self.safety_checker is not None:
            safety = self.safety_checker.check(ingredients, user_profile)
            if not safety["is_safe"]:
                return {"score": -999.0, "reject": True, "reason": safety["issues"], "nutrition": nutrition}

        calorie_fit = self._calorie_fit_score(nutrition["calories"], slot_target_calories)
        macro_fit = self._macro_fit_score(nutrition, target_calories, goal)
        pref = self._preference_score(ingredients, user_profile)
        div = self._diversity_score(ingredients, user_profile)
        retrieval = clamp(float(recipe.get("score", 0.5)))
        goal_fit = self._goal_bonus(nutrition, goal)

        history_penalty = self._history_penalty(ingredients, user_profile)
        ingredient_penalty = self._ingredient_penalty(ingredients, user_profile)

        substitutions_used = recipe.get("substitutions", [])
        substitution_penalty = 0.0
        if substitutions_used:
            substitution_penalty = min(0.25, 0.05 * len(substitutions_used))

        final_score = (
            0.26 * calorie_fit +
            0.20 * macro_fit +
            0.18 * pref +
            0.14 * div +
            0.08 * retrieval +
            0.14 * goal_fit
            - history_penalty
            - ingredient_penalty
            - substitution_penalty
        )

        final_score = clamp(final_score, 0.0, 1.0)

        return {
            "score": final_score,
            "reject": False,
            "nutrition": nutrition,
            "components": {
                "calorie_fit": round(calorie_fit, 3),
                "macro_fit": round(macro_fit, 3),
                "preference": round(pref, 3),
                "diversity": round(div, 3),
                "retrieval": round(retrieval, 3),
                "goal_fit": round(goal_fit, 3),
                "history_penalty": round(history_penalty, 3),
                "ingredient_penalty": round(ingredient_penalty, 3),
                "substitution_penalty": round(substitution_penalty, 3),
            },
            "safety": safety,
        }

    # ==============================
    # DAY / WEEK BUILDING
    # ==============================

    def _apply_substitutions_if_needed(self, ingredients: List[str], user_profile) -> Dict[str, Any]:
        if self.substitution_engine is None:
            return {
                "ingredients": ingredients,
                "replacements": [],
            }

        result = self.substitution_engine.apply(
            ingredients=ingredients,
            user_profile=user_profile,
            cuisine=None,
        )

        return {
            "ingredients": result.get("ingredients", ingredients),
            "replacements": result.get("replacements", []),
        }

    def _build_day(
        self,
        day_number: int,
        user_profile,
        candidates: List[Dict[str, Any]],
        target_calories: int,
        macro_targets: Dict[str, float],
        meals_per_day: int,
    ) -> Dict[str, Any]:
        goal = self._normalize_goal(getattr(user_profile, "goal", "balanced"))
        weights = self._meal_weights(meals_per_day, goal)

        selected_signatures = set()
        meals: List[Dict[str, Any]] = []
        day_totals = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
        slot_candidates = list(candidates)

        for slot_idx in range(meals_per_day):
            slot_target = target_calories * weights[slot_idx]
            best = None
            best_score = -999.0

            for recipe in slot_candidates:
                ingredients = list(recipe["ingredients"])
                signature = self._recipe_signature(ingredients)

                if signature in selected_signatures:
                    continue

                substitution_result = self._apply_substitutions_if_needed(ingredients, user_profile)
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
                )

                if scored.get("reject"):
                    continue

                if scored["score"] > best_score:
                    best_score = scored["score"]
                    best = {
                        "name": temp_recipe["name"],
                        "ingredients": adjusted_ingredients,
                        "nutrition": scored["nutrition"],
                        "score": scored["score"],
                        "components": scored["components"],
                        "warnings": scored.get("safety", {}).get("warnings", []) if scored.get("safety") else [],
                        "issues": scored.get("safety", {}).get("issues", []) if scored.get("safety") else [],
                        "replacements": substitution_result["replacements"],
                        "instructions": temp_recipe.get("instructions", []),
                        "cuisine": temp_recipe.get("cuisine"),
                    }

            if best is None:
                continue

            selected_signatures.add(self._recipe_signature(best["ingredients"]))
            meals.append(best)

            day_totals["calories"] += best["nutrition"]["calories"]
            day_totals["protein"] += best["nutrition"]["protein"]
            day_totals["fat"] += best["nutrition"]["fat"]
            day_totals["carbs"] += best["nutrition"]["carbs"]

        day_score = 0.0
        if meals:
            day_score = sum(m["score"] for m in meals) / len(meals)

        return {
            "day": day_number,
            "target_calories": target_calories,
            "macro_targets": macro_targets,
            "meals": meals,
            "day_total": {
                "calories": round(day_totals["calories"], 1),
                "protein": round(day_totals["protein"], 1),
                "fat": round(day_totals["fat"], 1),
                "carbs": round(day_totals["carbs"], 1),
            },
            "day_score": round(day_score, 3),
        }

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
