import argparse
import logging
from pathlib import Path

import numpy as np
import torch
from PIL import Image
import open_clip
import faiss

from ai.food_normalizer.normalizer import FoodNormalizer
from ai.yolo.inference.crop_food import crop_food
from ai.recipes.recipe_search import RecipeSearch
from ai.llm.llm_service import FoodLLM
from ai.llm.nutrition_engine import NutritionEngine

from ai.core.decision.safety_checker import SafetyChecker
from ai.core.decision.preference_scorer import PreferenceScorer
from ai.core.decision.ranking_engine import RankingEngine
from ai.core.decision.diversity_engine import DiversityEngine
from ai.core.decision.ingredient_scorer import IngredientScorer
from ai.core.decision.substitution_engine import SubstitutionEngine

from ai.core.meal_planner import MealPlanner
from ai.core.user_profile import UserProfile

# ==============================
# CONFIG
# ==============================

BASE_DIR = Path(__file__).resolve().parents[2]

FAISS_INDEX_PATH = BASE_DIR / "ai/clip/index/food_index.faiss"
LABELS_PATH = BASE_DIR / "ai/clip/embeddings/food_labels.npy"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FoodRecognizer")

# ==============================
# GLOBAL CACHE
# ==============================

_clip_model = None
_preprocess = None
_index = None
_labels = None

# ==============================
# MODULES
# ==============================

normalizer = FoodNormalizer()
recipe_search = RecipeSearch()
llm = FoodLLM()
nutrition_engine = NutritionEngine()

safety_checker = SafetyChecker()
preference_scorer = PreferenceScorer()
ranking_engine = RankingEngine()
diversity_engine = DiversityEngine()
ingredient_scorer = IngredientScorer()
substitution_engine = SubstitutionEngine()

meal_planner = MealPlanner(
    recipe_search=recipe_search,
    nutrition_engine=nutrition_engine,
    llm=llm,
    safety_checker=safety_checker,
    preference_scorer=preference_scorer,
    diversity_engine=diversity_engine,
    substitution_engine=substitution_engine,
    ranking_engine=ranking_engine
)

# ==============================
# LOAD CLIP
# ==============================

from ai.core.models.clip_loader import get_clip

def load_clip(model_name="ViT-L-14", pretrained="openai"):
    global _clip_model, _preprocess

    if _clip_model is None:
        logger.info("Loading CLIP model...")

        model, tokenizer, preprocess = get_clip(model_name)

        model = model.to(DEVICE)
        model.eval()

        _clip_model = model
        _preprocess = preprocess

    return _clip_model, _preprocess


# ==============================
# LOAD FAISS
# ==============================

def load_faiss():
    global _index, _labels

    if _index is None:
        _index = faiss.read_index(str(FAISS_INDEX_PATH))

    if _labels is None:
        _labels = np.load(LABELS_PATH, allow_pickle=True)

    return _index, _labels


# ==============================
# ENCODE IMAGES
# ==============================

def encode_images(image_paths, batch_size=32):
    clip_model, preprocess = load_clip()

    tensors = []
    valid_paths = []

    for path in image_paths:
        try:
            img = Image.open(path).convert("RGB")
            tensors.append(preprocess(img))
            valid_paths.append(path)
        except:
            continue

    if not tensors:
        return [], []

    embeddings = []

    with torch.no_grad():
        for i in range(0, len(tensors), batch_size):
            batch = torch.stack(tensors[i:i + batch_size]).to(DEVICE)

            feats = clip_model.encode_image(batch)
            feats = feats.cpu().numpy()
            feats = feats / (np.linalg.norm(feats, axis=1, keepdims=True) + 1e-10)

            embeddings.extend(feats)

    return embeddings, valid_paths


# ==============================
# CLIP FALLBACK
# ==============================

def infer_dish_with_clip(ingredients):
    return f"{', '.join(ingredients)} dish"


# ==============================
# MAIN
# ==============================

def recognize_food(image_path, user_profile=None, top_k=5):

    logger.info("Running YOLO...")
    crops_data = crop_food(image_path)

    if user_profile is None:
        user_profile = UserProfile(
            age=25,
            sex="male",
            height_cm=180,
            weight_kg=75,
            activity_level="moderate",
            allergies=[],
            disliked_ingredients=[],
            preferred_ingredients=[],
            goal="balanced"
        )

    if not crops_data:
        return None


    crops = [c["path"] for c in crops_data]
    yolo_labels = [c["label"].lower() for c in crops_data]

    embeddings, valid_paths = encode_images(crops)

    # ==============================
    # NORMALIZATION
    # ==============================

    all_normalized = [normalizer.normalize(e) for e in embeddings]

    scored = ingredient_scorer.combine(yolo_labels, all_normalized)
    ingredients = [i["name"] for i in scored if i["score"] > 0.3][:5]

    if not ingredients:
        ingredients = yolo_labels

    goal = user_profile.goal

    # ==============================
    # SUBSTITUTION
    # ==============================

    sub_result = substitution_engine.apply(ingredients, user_profile)
    ingredients = sub_result["ingredients"]

    # ==============================
    # SAFETY
    # ==============================

    safety = safety_checker.check(ingredients, user_profile)

    if not safety["is_safe"]:
        return {"status": "unsafe", "issues": safety}

    # ==============================
    # LLM DISH NAME
    # ==============================

    prompt = f"""
Given ingredients: {ingredients}
Goal: {goal}

Return JSON:
{{
  "dish_name": "..."
}}
"""

    dish_data = llm.generate_json(prompt)
    meal_name = dish_data.get("dish_name", infer_dish_with_clip(ingredients))

    # ==============================
    # RECIPE (LLM SAFE)
    # ==============================

    recipe_prompt = f"""
    You are a strict cooking AI.

    Ingredients: {ingredients}
    Goal: {goal}

    Rules:
    - Use ONLY provided ingredients
    - Do NOT add new ingredients
    - Keep recipe simple

    Return JSON:
    {{
    "steps": ["step 1", "step 2"],
    "tips": "..."
    }}
    """

    recipe_data = llm.generate_recipe(ingredients, goal)

    # fallback защита
    if "steps" not in recipe_data:
        recipe_data = {
            "steps": [],
            "tips": ""
        }
    # нормализация
    recipe_data["steps"] = [
        str(s).strip() for s in recipe_data.get("steps", []) if s
    ]

    recipe_data["tips"] = str(recipe_data.get("tips", "")).strip()

    # ==============================
    # NUTRITION
    # ==============================

    nutrition = nutrition_engine.calculate(ingredients)

    # ==============================
    # SCORING
    # ==============================

    pref = preference_scorer.score(ingredients, user_profile)
    div = diversity_engine.score(ingredients, user_profile)
    nut = ranking_engine.score_nutrition(nutrition, goal)

    final_score = ranking_engine.combine(pref, div, nut)

    # ==============================
    # HISTORY
    # ==============================

    user_profile.add_meal(ingredients)

    # ==============================
    # MEAL PLAN
    # ==============================

    meal_plan = meal_planner.build_plan(user_profile=user_profile, days=3)

    # ==============================
    # OUTPUT
    # ==============================

    def clean_output(obj):
        if isinstance(obj, dict):
            return {k: clean_output(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_output(v) for v in obj]
        elif isinstance(obj, str):
            try:
                return obj.encode("latin1").decode("utf-8")
            except:
                return obj
        return obj

    result = {
        "meal": meal_name,
        "ingredients": ingredients,
        "nutrition": nutrition,
        "score": final_score,
        "recipe": recipe_data,
        "meal_plan": meal_plan,
        "safety": safety,
        "substitutions": sub_result["replacements"]
    }

    return clean_output(result)


# ==============================
# CLI
# ==============================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")

    args = parser.parse_args()

    result = recognize_food(args.image)

    print("\n=== RESULT ===")
    print(result)