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
from ai.core.meal_builder import MealBuilder
from ai.recipes.recipe_search import RecipeSearch
from ai.llm.llm_service import FoodLLM
from ai.llm.prompts import build_prompt
from ai.llm.nutrition_engine import NutritionEngine
from ai.core.decision.safety_checker import SafetyChecker
from ai.core.decision.preference_scorer import PreferenceScorer
from ai.core.decision.ranking_engine import RankingEngine
from ai.core.decision.diversity_engine import DiversityEngine

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
meal_builder = MealBuilder()
recipe_search = RecipeSearch()
llm = FoodLLM()
nutrition_engine = NutritionEngine()
safety_checker = SafetyChecker()
preference_scorer = PreferenceScorer()
ranking_engine = RankingEngine()

# ==============================
# LOAD CLIP
# ==============================

def load_clip(model_name="ViT-L-14", pretrained="openai"):
    global _clip_model, _preprocess

    if _clip_model is None:
        logger.info("Loading CLIP model...")

        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name,
            pretrained=pretrained
        )

        model = model.to(DEVICE)
        model.eval()

        _clip_model = model
        _preprocess = preprocess

    return _clip_model, _preprocess


# ==============================
# LOAD FAISS (image index)
# ==============================

def load_faiss():
    global _index, _labels

    if _index is None:
        if not FAISS_INDEX_PATH.exists():
            raise FileNotFoundError(f"FAISS index not found: {FAISS_INDEX_PATH}")

        logger.info("Loading FAISS index...")
        _index = faiss.read_index(str(FAISS_INDEX_PATH))

    if _labels is None:
        if not LABELS_PATH.exists():
            raise FileNotFoundError(f"Labels file not found: {LABELS_PATH}")

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
            tensor = preprocess(img)

            tensors.append(tensor)
            valid_paths.append(path)

        except Exception as e:
            logger.warning(f"Cannot load image {path}: {e}")

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
# IMAGE FAISS SEARCH (debug)
# ==============================

def search_embeddings(embeddings, top_k=5):
    index, labels = load_faiss()

    results = []

    for emb in embeddings:
        emb = emb.astype("float32").reshape(1, -1)

        distances, indices = index.search(emb, top_k)

        matches = []
        for score, idx in zip(distances[0], indices[0]):
            matches.append({
                "label": labels[idx],
                "score": float(score)
            })

        results.append(matches)

    return results


# ==============================
# CLIP DISH INFERENCE (fallback)
# ==============================

def infer_dish_with_clip(ingredients):
    clip_model, _ = load_clip()
    tokenizer = open_clip.get_tokenizer("ViT-L-14")

    query = f"a dish with {', '.join(ingredients)}"

    with torch.no_grad():
        tokens = tokenizer([query]).to(DEVICE)
        emb = clip_model.encode_text(tokens)
        emb = emb.cpu().numpy()

    emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-10)

    return query


# ==============================
# MAIN PIPELINE
# ==============================

def recognize_food(
    image_path,
    top_k=5,
    preferences=None,
    restrictions=None,
    goal=None
):
    logger.info("Running YOLO segmentation...")

    crops_data = crop_food(image_path)

    if not crops_data:
        logger.warning("No food detected.")
        return None

    crops = [c["path"] for c in crops_data]
    yolo_labels = [c["label"].lower() for c in crops_data]

    logger.info(f"YOLO labels: {yolo_labels}")
    logger.info(f"{len(crops)} food objects detected")

    if not crops:
        logger.warning("No food detected.")
        return None

    logger.info(f"{len(crops)} food objects detected")

    # ==============================
    # CLIP embeddings
    # ==============================

    embeddings, valid_paths = encode_images(crops)

    if not embeddings:
        logger.warning("No embeddings generated.")
        return None

    # ==============================
    # NORMALIZATION
    # ==============================

    all_normalized = []

    for emb, crop_path in zip(embeddings, valid_paths):
        results = normalizer.normalize(emb)
        all_normalized.append(results)

        logger.info(f"\n{crop_path}")
        for r in results:
            logger.info(f"  {r['name']} ({r['score']:.3f})")

    # ==============================
    # AGGREGATION
    # ==============================

    aggregated = normalizer.aggregate(all_normalized)

    ingredients_with_scores = [
        {"name": name, "score": score}
        for name, score in aggregated
        if score > 0.3   # Фильтр шума
    ][:5]

    # ==============================
    # MERGE CLIP + YOLO (FIX)
    # ==============================

    clip_ingredients = [i["name"] for i in ingredients_with_scores]

    # Взвешенное объединение
    ingredients = list(set(clip_ingredients + yolo_labels))
    logger.info(f"CLIP ingredients: {clip_ingredients}")
    logger.info(f"Final merged ingredients: {ingredients}")

    # ==============================
    # DECISION LAYER (NEW)
    # ==============================

    from ai.core.user_profile import UserProfile

    user_profile = UserProfile(
        allergies=[],
        preferred_ingredients=["chicken", "rice"],
        goal=goal
    )

    # SAFETY CHECK
    safety = safety_checker.check(ingredients, user_profile)

    if not safety["is_safe"]:
        logger.warning(f"Unsafe food detected: {safety['issues']}")
        return {
            "status": "unsafe",
            "issues": safety["issues"],
            "ingredients": ingredients
        }

    # PREFERENCE SCORE
    pref_score = preference_scorer.score(ingredients, user_profile)

    # ==============================
    # MEAL BUILDER (fallback)
    # ==============================

    meal_name = meal_builder.build_meal(ingredients)
    cuisine = meal_builder.detect_cuisine(ingredients)

    if meal_name == " ".join(ingredients[:2]):
        logger.info("Using CLIP fallback for dish inference...")
        meal_name = infer_dish_with_clip(ingredients)

    # ==============================
    # RECIPE SEARCH (secondary)
    # ==============================

    query = f"{meal_name} with {', '.join(ingredients)}"
    recipes = recipe_search.search(query, top_k=3)

    # ==============================
    # LLM GENERATION (MAIN BRAIN)
    # ==============================

    preferences = preferences or "balanced"
    restrictions = restrictions or "none"
    goal = goal or "healthy eating"

    prompt = build_prompt(
        ingredients=ingredients,
        preferences=preferences,
        restrictions=restrictions,
        goal=goal
    )

    dish_data = llm.generate_dish(ingredients, goal)
    recipe_data = llm.generate_recipe(ingredients, goal)

    llm_result = {
        **dish_data,
        "recipe": recipe_data
    }

    # ==============================
    # VALIDATE LLM OUTPUT (CRITICAL)
    # ==============================

    if isinstance(llm_result, dict):

        llm_ingredients = llm_result.get("ingredients", [])

        # нормализуем в lowercase
        llm_ingredients = [i.lower() for i in llm_ingredients]

        base_ingredients = [i.lower() for i in ingredients]

        # проверяем: LLM не добавил лишнего
        if not all(i in base_ingredients for i in llm_ingredients):
            logger.warning("LLM hallucinated ingredients → REJECTED")

            llm_result["ingredients"] = ingredients
            llm_result["dish_name"] = " ".join(ingredients)

    logger.info(f"LLM Result: {llm_result}")

    # ==============================
    # APPLY LLM OUTPUT
    # ==============================

    if isinstance(llm_result, dict):

        if llm_result.get("dish_name"):
            meal_name = llm_result["dish_name"]

    # ==============================
    # NUTRITION ENGINE (REAL DATA)
    # ==============================

    nutrition = nutrition_engine.calculate(ingredients)

    if isinstance(llm_result, dict):
        llm_result["calories"] = nutrition["calories"]
        llm_result["protein"] = nutrition["protein"]
        llm_result["fat"] = nutrition["fat"]
        llm_result["carbs"] = nutrition["carbs"]

    # ==============================
    # NUTRITION SCORE (TOP)
    # ==============================

    nutrition_score = ranking_engine.score_nutrition(
        nutrition,
        goal=user_profile.goal
    )

    # ==============================
    # DEBUG FAISS
    # ==============================

    matches = search_embeddings(embeddings, top_k)

    # ==============================
    # FINAL RANKING (TOP VERSION)
    # ==============================

    from ai.core.decision.diversity_engine import DiversityEngine

    diversity_engine = DiversityEngine()
    div_score = diversity_engine.score(ingredients, user_profile)

    final_score = ranking_engine.combine(
        pref_score=pref_score,
        diversity_score=div_score,
        nutrition_score=nutrition_score
    )

    # ==============================
    # OUTPUT
    # ==============================

    output = []

    for crop_path, result, norm in zip(valid_paths, matches, all_normalized):
        output.append({
            "crop_path": crop_path,
            "matches": result,
            "normalized": norm
        })

    return {
        "ingredients": ingredients,
        "meal": meal_name,
        "cuisine": cuisine,
        "recipes": recipes,
        "llm": llm_result,
        "nutrition": nutrition,
        "safety": safety,
        "score": final_score,
        "details": output
    }


# ==============================
# CLI
# ==============================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("image", help="Path to input image")

    parser.add_argument("--topk", type=int, default=5)

    args = parser.parse_args()

    result = recognize_food(args.image, args.topk)

    if not result:
        print("No food detected.")
        exit()

    print("\n=== FINAL RESULT ===")
    print("Meal:", result["meal"])
    print("Cuisine:", result["cuisine"])
    print("Ingredients:", result["ingredients"])

    print("\n=== SAFETY ===")
    print(result["safety"])

    print("\n=== SCORE ===")
    print(result["score"])

    print("\n=== NUTRITION ===")
    if result["llm"]:
        print("Calories:", result["llm"].get("calories"))
        print("Protein:", result["llm"].get("protein"))
        print("Fat:", result["llm"].get("fat"))
        print("Carbs:", result["llm"].get("carbs"))

    print("\n=== RECIPES ===")
    for r in result["recipes"]:
        print(f"\n{r['name']} (score={r['score']:.3f})")
        print("Ingredients:", ", ".join(r["ingredients"]))
        print("Instructions:", r["instructions"])