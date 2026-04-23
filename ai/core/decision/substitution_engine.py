import json
from pathlib import Path
from typing import List, Dict


class SubstitutionEngine:

    def __init__(self):
        self.ALLOW_SUBSTITUTION_FOR_ALLERGIES = True

        # путь к JSON
        base_dir = Path(__file__).resolve().parents[2]
        self.data_path = base_dir / "data" / "substitutions.json"

        self.substitutions = self._load_data()

    # ==============================
    # LOAD JSON
    # ==============================
    def _load_data(self):
        if not self.data_path.exists():
            raise FileNotFoundError(f"Substitution file not found: {self.data_path}")

        with open(self.data_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ==============================
    # MAIN
    # ==============================
    
    def apply(self, ingredients: List[str], user_profile, cuisine: str = None) -> Dict:
        new_ingredients = []
        replacements = []
        allergies = set(i.lower() for i in getattr(user_profile, "allergies", []))
        disliked = set(i.lower() for i in getattr(user_profile, "disliked_ingredients", []))
        excluded = set(i.lower() for i in getattr(user_profile, "excluded_ingredients", []))

        context = {
            "goal": getattr(user_profile, "goal", None),
            "cuisine": cuisine,
            "restrictions": {
                "allergies": allergies,
                "disliked": disliked,
                "excluded": excluded
            }
        }

        for ing in ingredients:
            ing = ing.lower()

            if ing in excluded:
                continue

            if ing in allergies:
                if not self.ALLOW_SUBSTITUTION_FOR_ALLERGIES:
                    continue

                substitute = self._get_best_substitute(ing, context)
                if substitute:
                    replacements.append({"from": ing, "to": substitute, "reason": "allergy"})
                    new_ingredients.append(substitute)
                else:
                    new_ingredients.append(ing)
                continue
            
            if ing in disliked:
                substitute = self._get_best_substitute(ing, context)
                if substitute:
                    replacements.append({"from": ing, "to": substitute, "reason": "disliked"})
                    new_ingredients.append(substitute)
                else:
                    new_ingredients.append(ing)
                continue

            new_ingredients.append(ing)

        ordered = []
        seen = set()
        for ing in new_ingredients:
            if ing not in seen:
                ordered.append(ing)
                seen.add(ing)

        return {
            "ingredients": ordered,
            "replacements": replacements
        }

    # ==============================
    # SHOULD REPLACE
    # ==============================
    def _should_replace(self, ingredient: str, user_profile) -> bool:

        if ingredient in getattr(user_profile, "allergies", []):
            return self.ALLOW_SUBSTITUTION_FOR_ALLERGIES

        if ingredient in getattr(user_profile, "disliked_ingredients", []):
            return True

        return False

    # ==============================
    # GET BEST SUBSTITUTE
    # ==============================
    def _get_best_substitute(self, ingredient: str, context: dict):

        candidates = self.substitutions.get(ingredient, [])

        if not candidates:
            return None

        scored = []

        for candidate in candidates:
            score = self._score_candidate(candidate, context)
            scored.append((candidate["item"], score))

        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[0][0] if scored else None

    # ==============================
    # SCORING
    # ==============================
    def _score_candidate(self, candidate: dict, context: dict) -> float:
        score = candidate.get("base_score", 0.5)

        # кухня
        if context["cuisine"]:
            if "any" in candidate.get("cuisine", []):
                score += 0.1
            elif context["cuisine"] in candidate.get("cuisine", []):
                score += 0.3

        # цель
        if context["goal"] == "muscle_gain":
            if "meat" in candidate.get("tags", []):
                score += 0.3

        if context["goal"] == "diet":
            if "vegan" in candidate.get("tags", []):
                score += 0.2

        # ограничения (например веган)
        if "vegan" in context["restrictions"]:
            if "vegan" in candidate.get("tags", []):
                score += 0.3
            else:
                score -= 0.5

        return score

    # ==============================
    # REASON
    # ==============================
    def _get_reason(self, ingredient: str, user_profile) -> str:
        if ingredient in getattr(user_profile, "allergies", []):
            return "allergy"
        if ingredient in getattr(user_profile, "disliked_ingredients", []):
            return "disliked"
        return "replacement"