# ai/recipes/build_index.py
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
import torch
import open_clip


# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────

THIS_FILE = Path(__file__).resolve()
RECIPES_DIR = THIS_FILE.parent
AI_DIR = RECIPES_DIR.parent
PROJECT_ROOT = AI_DIR.parent

DEFAULT_RECIPES_JSON = RECIPES_DIR / "recipes.json"
DEFAULT_INDEX_PATH = RECIPES_DIR / "recipe_index.faiss"
DEFAULT_EMBEDDINGS_PATH = RECIPES_DIR / "recipe_embeddings.npy"
DEFAULT_META_PATH = RECIPES_DIR / "recipe_index_meta.json"
DEFAULT_REPORT_PATH = RECIPES_DIR / "recipe_index_report.json"

DATA_DIR = AI_DIR / "data"
LLM_DIR = AI_DIR / "llm"

REFERENCE_SEARCH_DIRS = [
    DATA_DIR,
    LLM_DIR,
    RECIPES_DIR,
]


# ──────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────

logger = logging.getLogger("RecipeIndexBuilder")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )


# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

@dataclass
class BuildConfig:
    recipes_json: Path
    index_path: Path
    embeddings_path: Path
    meta_path: Path
    report_path: Path

    model_name: str = "ViT-L-14"
    pretrained: str = "openai"
    batch_size: int = 64
    device: str = "auto"

    strict: bool = False
    backup_old: bool = True
    min_embedding_text_len: int = 12

    legacy_root_copy: bool = False


# ──────────────────────────────────────────────
# JSON HELPERS
# ──────────────────────────────────────────────

def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid JSON: {path}\n"
            f"Line {e.lineno}, column {e.colno}: {e.msg}"
        ) from e


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_optional_json(filename: str) -> Optional[Path]:
    for folder in REFERENCE_SEARCH_DIRS:
        candidate = folder / filename
        if candidate.exists():
            return candidate
    return None


def load_optional_dict(filename: str) -> Dict[str, Any]:
    path = find_optional_json(filename)
    if path is None:
        logger.warning("Optional reference file not found: %s", filename)
        return {}

    try:
        data = load_json(path)
    except Exception as e:
        logger.warning("Failed to load optional reference %s: %s", path, e)
        return {}

    if not isinstance(data, dict):
        logger.warning("Optional reference is not dict: %s", path)
        return {}

    logger.info("Loaded reference: %s", path)
    return data


# ──────────────────────────────────────────────
# NORMALIZATION
# ──────────────────────────────────────────────

_SPACE_RE = re.compile(r"\s+")
_BAD_CHARS_RE = re.compile(r"[^a-z0-9_]+")


def normalize_key(value: Any) -> str:
    """
    Приводит названия к виду:
    'Chicken Breast' -> 'chicken_breast'
    'soy sauce' -> 'soy_sauce'
    'coconut_milk_(optional)' -> 'coconut_milk_optional'

    ВАЖНО:
    Это не заменяет food_aliases.json.
    Это только техническая нормализация ключа.
    """
    if value is None:
        return ""

    text = str(value).strip().lower()
    text = text.replace("-", "_")
    text = text.replace("/", "_")
    text = text.replace("(", "_")
    text = text.replace(")", "_")
    text = text.replace(",", "_")
    text = _SPACE_RE.sub("_", text)
    text = _BAD_CHARS_RE.sub("_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def normalize_display_text(value: Any) -> str:
    if value is None:
        return ""
    return _SPACE_RE.sub(" ", str(value).strip())


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# ──────────────────────────────────────────────
# RECIPE LOADING
# ──────────────────────────────────────────────

def extract_recipes(raw: Any) -> List[Dict[str, Any]]:
    """
    Поддерживает:
    1. [ {...}, {...} ]
    2. { "recipes": [ {...}, {...} ] }
    """
    if isinstance(raw, list):
        recipes = raw
    elif isinstance(raw, dict) and isinstance(raw.get("recipes"), list):
        recipes = raw["recipes"]
    else:
        raise ValueError(
            "recipes.json must be either a list of recipes or object with key 'recipes'."
        )

    result = []
    for idx, item in enumerate(recipes):
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict recipe at index %s", idx)
            continue
        result.append(item)

    return result


# ──────────────────────────────────────────────
# REFERENCE VALIDATION
# ──────────────────────────────────────────────

def build_alias_map(food_aliases: Dict[str, Any]) -> Dict[str, str]:
    """
    Ожидаемый формат:
    {
      "chicken_breast": "chicken",
      "ground_beef": "beef"
    }

    Поддерживает также вложенный формат, если вдруг появится:
    {
      "aliases": {
        "chicken_breast": "chicken"
      }
    }
    """
    if "aliases" in food_aliases and isinstance(food_aliases["aliases"], dict):
        food_aliases = food_aliases["aliases"]

    alias_map: Dict[str, str] = {}

    for src, dst in food_aliases.items():
        if not isinstance(dst, str):
            continue

        src_key = normalize_key(src)
        dst_key = normalize_key(dst)

        if src_key and dst_key:
            alias_map[src_key] = dst_key

    return alias_map


def resolve_alias(name: str, alias_map: Dict[str, str]) -> str:
    key = normalize_key(name)
    seen = set()

    while key in alias_map and key not in seen:
        seen.add(key)
        key = alias_map[key]

    return key


def collect_reference_keys(reference: Dict[str, Any], alias_map: Dict[str, str]) -> set[str]:
    keys = set()

    for key in reference.keys():
        norm = normalize_key(key)
        resolved = resolve_alias(norm, alias_map)
        if norm:
            keys.add(norm)
        if resolved:
            keys.add(resolved)

    return keys


# ──────────────────────────────────────────────
# EMBEDDING TEXT
# ──────────────────────────────────────────────

def get_ingredient_names(recipe: Dict[str, Any]) -> List[str]:
    names: List[str] = []

    details = recipe.get("ingredients_detail")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue

            canonical = item.get("canonical_name")
            name = item.get("name")
            value = canonical or name

            if value:
                names.append(normalize_key(value))

    if names:
        return sorted(set(names))

    raw_ingredients = recipe.get("ingredients", [])
    for item in as_list(raw_ingredients):
        if isinstance(item, str):
            names.append(normalize_key(item))
        elif isinstance(item, dict):
            value = item.get("canonical_name") or item.get("name")
            if value:
                names.append(normalize_key(value))

    return sorted(set([x for x in names if x]))


def get_core_ingredients(recipe: Dict[str, Any]) -> List[str]:
    profile = recipe.get("search_profile") or {}
    core = profile.get("core_ingredients")

    if isinstance(core, list) and core:
        return [normalize_key(x) for x in core if normalize_key(x)]

    result = []
    details = recipe.get("ingredients_detail")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue

            is_core = bool(item.get("is_core", False))
            role = normalize_key(item.get("role", ""))

            if is_core or role in {
                "main_protein",
                "main_carb",
                "main_vegetable",
                "main_fat",
                "protein",
                "carb",
                "vegetable",
            }:
                value = item.get("canonical_name") or item.get("name")
                if value:
                    result.append(normalize_key(value))

    if result:
        return sorted(set(result))

    return get_ingredient_names(recipe)[:4]


def get_secondary_ingredients(recipe: Dict[str, Any]) -> List[str]:
    profile = recipe.get("search_profile") or {}
    secondary = profile.get("secondary_ingredients")

    if isinstance(secondary, list):
        return [normalize_key(x) for x in secondary if normalize_key(x)]

    core = set(get_core_ingredients(recipe))
    all_names = get_ingredient_names(recipe)

    excluded_roles = {
        "seasoning",
        "garnish",
        "spice",
        "herb",
    }

    result = []
    details = recipe.get("ingredients_detail")

    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue

            value = item.get("canonical_name") or item.get("name")
            name = normalize_key(value)
            role = normalize_key(item.get("role", ""))

            if not name or name in core:
                continue
            if role in excluded_roles:
                continue

            result.append(name)

    if result:
        return sorted(set(result))

    return [x for x in all_names if x not in core][:4]


def build_embedding_text(recipe: Dict[str, Any]) -> str:
    """
    Главный источник:
    recipe["search_profile"]["embedding_text"]

    Fallback строится так, чтобы embeddings понимали блюдо,
    а не мусор из инструкций.
    """
    profile = recipe.get("search_profile") or {}

    explicit_text = profile.get("embedding_text")
    if isinstance(explicit_text, str) and explicit_text.strip():
        return normalize_display_text(explicit_text)

    name = normalize_display_text(
        recipe.get("display_name") or recipe.get("name") or recipe.get("id")
    )

    cuisine = normalize_display_text(recipe.get("cuisine") or "generic")
    dish_type = normalize_display_text(recipe.get("dish_type") or "")
    meal_types = [normalize_key(x) for x in as_list(recipe.get("meal_types")) if normalize_key(x)]
    diet_tags = [normalize_key(x) for x in as_list(recipe.get("diet_tags")) if normalize_key(x)]
    suitable_for = [normalize_key(x) for x in as_list(recipe.get("suitable_for")) if normalize_key(x)]

    core = get_core_ingredients(recipe)
    secondary = get_secondary_ingredients(recipe)

    parts = [name]

    if core:
        parts.append("Main ingredients: " + ", ".join(core) + ".")
    if secondary:
        parts.append("Secondary ingredients: " + ", ".join(secondary) + ".")
    if cuisine:
        parts.append(f"Cuisine: {cuisine}.")
    if dish_type:
        parts.append(f"Dish type: {dish_type}.")
    if meal_types:
        parts.append("Meal types: " + ", ".join(meal_types) + ".")
    if diet_tags:
        parts.append("Diet tags: " + ", ".join(diet_tags) + ".")
    if suitable_for:
        parts.append("Suitable for: " + ", ".join(suitable_for) + ".")

    return normalize_display_text(" ".join(parts))


# ──────────────────────────────────────────────
# VALIDATION
# ──────────────────────────────────────────────

def validate_recipe(
    recipe: Dict[str, Any],
    index: int,
    seen_ids: set[str],
    nutrition_keys: set[str],
    food_group_keys: set[str],
    portion_keys: set[str],
    alias_map: Dict[str, str],
    min_embedding_text_len: int,
) -> Tuple[bool, Dict[str, Any]]:
    errors: List[str] = []
    warnings: List[str] = []

    recipe_id = normalize_key(recipe.get("id"))
    name = normalize_display_text(recipe.get("name") or recipe.get("display_name"))

    if not recipe_id:
        errors.append("missing_id")
        recipe_id = f"missing_id_{index}"

    if recipe_id in seen_ids:
        errors.append("duplicate_id")
    else:
        seen_ids.add(recipe_id)

    if not name:
        warnings.append("missing_name")

    ingredients = recipe.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        warnings.append("missing_or_empty_ingredients")

    ingredients_detail = recipe.get("ingredients_detail")
    if not isinstance(ingredients_detail, list) or not ingredients_detail:
        warnings.append("missing_or_empty_ingredients_detail")

    serving_model = recipe.get("serving_model")
    if not isinstance(serving_model, dict):
        warnings.append("missing_serving_model")
    else:
        if not serving_model.get("default_servings"):
            warnings.append("serving_model_missing_default_servings")
        if not serving_model.get("grams_scope"):
            warnings.append("serving_model_missing_grams_scope")

    nutrition = recipe.get("nutrition")
    if not isinstance(nutrition, dict):
        warnings.append("missing_nutrition_block")
    else:
        if nutrition.get("needs_recompute") is True:
            warnings.append("nutrition_needs_recompute")
        if nutrition.get("per_serving") is None:
            warnings.append("nutrition_per_serving_empty")

    embedding_text = build_embedding_text(recipe)
    if len(embedding_text) < min_embedding_text_len:
        errors.append("embedding_text_too_short")

    canonical_names = []
    if isinstance(ingredients_detail, list):
        for item in ingredients_detail:
            if not isinstance(item, dict):
                warnings.append("ingredients_detail_item_not_dict")
                continue

            canonical = item.get("canonical_name") or item.get("name")
            canonical_norm = normalize_key(canonical)
            canonical_resolved = resolve_alias(canonical_norm, alias_map)

            if not canonical_resolved:
                warnings.append("empty_canonical_name")
                continue

            canonical_names.append(canonical_resolved)

            if nutrition_keys and canonical_resolved not in nutrition_keys:
                warnings.append(f"missing_in_nutrition_db:{canonical_resolved}")

            if food_group_keys and canonical_resolved not in food_group_keys:
                warnings.append(f"missing_in_food_groups:{canonical_resolved}")

            if portion_keys and canonical_resolved not in portion_keys:
                warnings.append(f"missing_in_portion_rules:{canonical_resolved}")

            grams = item.get("grams")
            if grams is None:
                warnings.append(f"missing_grams:{canonical_resolved}")
            else:
                try:
                    grams_f = float(grams)
                    if grams_f <= 0:
                        warnings.append(f"non_positive_grams:{canonical_resolved}")
                except Exception:
                    warnings.append(f"invalid_grams:{canonical_resolved}")

    search_profile = recipe.get("search_profile")
    if not isinstance(search_profile, dict):
        warnings.append("missing_search_profile")
    else:
        if not search_profile.get("embedding_text"):
            warnings.append("missing_search_profile_embedding_text_using_fallback")

    metadata = {
        "index": index,
        "id": recipe_id,
        "name": name,
        "embedding_text": embedding_text,
        "embedding_text_len": len(embedding_text),
        "canonical_names": sorted(set(canonical_names)),
        "errors": errors,
        "warnings": sorted(set(warnings)),
    }

    is_valid = len(errors) == 0
    return is_valid, metadata


def validate_recipes(
    recipes: List[Dict[str, Any]],
    config: BuildConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    food_aliases = load_optional_dict("food_aliases.json")
    nutrition_db = load_optional_dict("nutrition_db.json")
    food_groups = load_optional_dict("food_groups.json")
    portion_rules = load_optional_dict("portion_rules.json")

    alias_map = build_alias_map(food_aliases)

    nutrition_keys = collect_reference_keys(nutrition_db, alias_map)
    food_group_keys = collect_reference_keys(food_groups, alias_map)
    portion_keys = collect_reference_keys(portion_rules, alias_map)

    seen_ids: set[str] = set()
    valid_recipes: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []

    total_errors = 0
    total_warnings = 0
    warning_counts: Dict[str, int] = {}
    error_counts: Dict[str, int] = {}

    for idx, recipe in enumerate(recipes):
        is_valid, meta = validate_recipe(
            recipe=recipe,
            index=idx,
            seen_ids=seen_ids,
            nutrition_keys=nutrition_keys,
            food_group_keys=food_group_keys,
            portion_keys=portion_keys,
            alias_map=alias_map,
            min_embedding_text_len=config.min_embedding_text_len,
        )

        for err in meta["errors"]:
            error_counts[err] = error_counts.get(err, 0) + 1

        for warn in meta["warnings"]:
            key = warn.split(":", 1)[0]
            warning_counts[key] = warning_counts.get(key, 0) + 1

        total_errors += len(meta["errors"])
        total_warnings += len(meta["warnings"])
        metas.append(meta)

        if is_valid:
            valid_recipes.append(recipe)

    report = {
        "recipes_total": len(recipes),
        "recipes_valid_for_index": len(valid_recipes),
        "recipes_invalid": len(recipes) - len(valid_recipes),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "error_counts": dict(sorted(error_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
        "references": {
            "food_aliases_loaded": bool(food_aliases),
            "nutrition_db_loaded": bool(nutrition_db),
            "food_groups_loaded": bool(food_groups),
            "portion_rules_loaded": bool(portion_rules),
            "alias_count": len(alias_map),
            "nutrition_db_keys": len(nutrition_keys),
            "food_group_keys": len(food_group_keys),
            "portion_rule_keys": len(portion_keys),
        },
    }

    return valid_recipes, metas, report


# ──────────────────────────────────────────────
# MODEL / EMBEDDINGS
# ──────────────────────────────────────────────

def resolve_device(device_arg: str) -> torch.device:
    if device_arg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_arg)


def load_clip_text_model(config: BuildConfig, device: torch.device):
    logger.info(
        "Loading open_clip model: model=%s pretrained=%s device=%s",
        config.model_name,
        config.pretrained,
        device,
    )

    model, _, _ = open_clip.create_model_and_transforms(
        config.model_name,
        pretrained=config.pretrained,
    )
    model.to(device)
    model.eval()

    tokenizer = open_clip.get_tokenizer(config.model_name)

    return model, tokenizer


def encode_texts(
    texts: List[str],
    model,
    tokenizer,
    device: torch.device,
    batch_size: int,
) -> np.ndarray:
    if not texts:
        raise ValueError("No texts to encode.")

    all_embeddings: List[np.ndarray] = []

    use_amp = device.type == "cuda"

    with torch.no_grad():
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]

            tokens = tokenizer(batch).to(device)

            if use_amp:
                with torch.cuda.amp.autocast():
                    emb = model.encode_text(tokens)
            else:
                emb = model.encode_text(tokens)

            emb = emb.float()
            emb = emb / emb.norm(dim=-1, keepdim=True).clamp_min(1e-12)

            all_embeddings.append(emb.cpu().numpy().astype("float32"))

            logger.info(
                "Encoded texts: %s/%s",
                min(start + batch_size, len(texts)),
                len(texts),
            )

    embeddings = np.vstack(all_embeddings).astype("float32")

    if embeddings.ndim != 2:
        raise ValueError(f"Expected 2D embeddings, got shape={embeddings.shape}")

    return embeddings


# ──────────────────────────────────────────────
# FAISS
# ──────────────────────────────────────────────

def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    if embeddings.dtype != np.float32:
        embeddings = embeddings.astype("float32")

    dim = embeddings.shape[1]

    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    return index


def backup_file(path: Path) -> Optional[Path]:
    if not path.exists():
        return None

    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def save_outputs(
    config: BuildConfig,
    index: faiss.Index,
    embeddings: np.ndarray,
    meta: Dict[str, Any],
    report: Dict[str, Any],
) -> None:
    config.index_path.parent.mkdir(parents=True, exist_ok=True)

    if config.backup_old:
        for path in [
            config.index_path,
            config.embeddings_path,
            config.meta_path,
            config.report_path,
        ]:
            backup = backup_file(path)
            if backup:
                logger.info("Backup created: %s", backup)

    np.save(config.embeddings_path, embeddings)
    faiss.write_index(index, str(config.index_path))
    save_json(config.meta_path, meta)
    save_json(config.report_path, report)

    logger.info("Saved embeddings: %s", config.embeddings_path)
    logger.info("Saved FAISS index: %s", config.index_path)
    logger.info("Saved meta: %s", config.meta_path)
    logger.info("Saved report: %s", config.report_path)

    if config.legacy_root_copy:
        root_index = PROJECT_ROOT / "recipe_index.faiss"
        root_embeddings = PROJECT_ROOT / "recipe_embeddings.npy"

        shutil.copy2(config.index_path, root_index)
        shutil.copy2(config.embeddings_path, root_embeddings)

        logger.warning("Legacy root copy enabled.")
        logger.warning("Copied index to: %s", root_index)
        logger.warning("Copied embeddings to: %s", root_embeddings)


# ──────────────────────────────────────────────
# BUILD PIPELINE
# ──────────────────────────────────────────────

def build_recipe_index(config: BuildConfig) -> Dict[str, Any]:
    logger.info("PROJECT_ROOT: %s", PROJECT_ROOT)
    logger.info("RECIPES_JSON: %s", config.recipes_json)

    raw = load_json(config.recipes_json)
    recipes = extract_recipes(raw)

    if not recipes:
        raise ValueError("No recipes found in recipes.json")

    valid_recipes, recipe_metas, validation_report = validate_recipes(recipes, config)

    if config.strict and validation_report["total_warnings"] > 0:
        raise RuntimeError(
            "Strict mode failed: warnings found.\n"
            f"Warning counts: {validation_report['warning_counts']}"
        )

    if validation_report["recipes_invalid"] > 0:
        logger.warning(
            "Invalid recipes skipped: %s",
            validation_report["recipes_invalid"],
        )

    if not valid_recipes:
        raise RuntimeError("No valid recipes left after validation.")

    valid_ids = set()
    valid_metas = []

    for meta in recipe_metas:
        if not meta["errors"]:
            valid_ids.add(meta["id"])
            valid_metas.append(meta)

    texts = [meta["embedding_text"] for meta in valid_metas]

    logger.info("Recipes total: %s", len(recipes))
    logger.info("Recipes valid for index: %s", len(valid_recipes))
    logger.info("Embedding texts: %s", len(texts))

    device = resolve_device(config.device)
    model, tokenizer = load_clip_text_model(config, device)

    embeddings = encode_texts(
        texts=texts,
        model=model,
        tokenizer=tokenizer,
        device=device,
        batch_size=config.batch_size,
    )

    index = build_faiss_index(embeddings)

    meta = {
        "schema_version": 3,
        "index_type": "faiss.IndexFlatIP",
        "similarity": "cosine_via_normalized_inner_product",
        "model": {
            "library": "open_clip",
            "model_name": config.model_name,
            "pretrained": config.pretrained,
            "embedding_dim": int(embeddings.shape[1]),
        },
        "source": {
            "recipes_json": str(config.recipes_json),
            "project_root": str(PROJECT_ROOT),
        },
        "counts": {
            "recipes_total": len(recipes),
            "recipes_indexed": len(valid_metas),
            "embeddings_shape": list(embeddings.shape),
            "faiss_ntotal": int(index.ntotal),
        },
        "items": [
            {
                "faiss_index": i,
                "recipe_id": item["id"],
                "name": item["name"],
                "embedding_text": item["embedding_text"],
                "canonical_names": item["canonical_names"],
                "warnings": item["warnings"],
            }
            for i, item in enumerate(valid_metas)
        ],
    }

    report = {
        "status": "ok",
        "validation": validation_report,
        "outputs": {
            "index_path": str(config.index_path),
            "embeddings_path": str(config.embeddings_path),
            "meta_path": str(config.meta_path),
            "report_path": str(config.report_path),
        },
        "top_warnings_examples": [
            {
                "id": item["id"],
                "name": item["name"],
                "warnings": item["warnings"][:10],
            }
            for item in valid_metas
            if item["warnings"]
        ][:25],
    }

    save_outputs(
        config=config,
        index=index,
        embeddings=embeddings,
        meta=meta,
        report=report,
    )

    return report


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build production FAISS index for recipes.json"
    )

    parser.add_argument(
        "--recipes",
        type=Path,
        default=DEFAULT_RECIPES_JSON,
        help="Path to recipes.json",
    )
    parser.add_argument(
        "--index-out",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="Output FAISS index path",
    )
    parser.add_argument(
        "--embeddings-out",
        type=Path,
        default=DEFAULT_EMBEDDINGS_PATH,
        help="Output numpy embeddings path",
    )
    parser.add_argument(
        "--meta-out",
        type=Path,
        default=DEFAULT_META_PATH,
        help="Output index metadata JSON path",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Output build report JSON path",
    )

    parser.add_argument(
        "--model",
        default="ViT-L-14",
        help="open_clip model name",
    )
    parser.add_argument(
        "--pretrained",
        default="openai",
        help="open_clip pretrained tag",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Text encoding batch size",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="auto, cpu, cuda",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any validation warnings are found",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not backup old output files",
    )
    parser.add_argument(
        "--legacy-root-copy",
        action="store_true",
        help="Also copy recipe_index.faiss and recipe_embeddings.npy to project root",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    config = BuildConfig(
        recipes_json=args.recipes,
        index_path=args.index_out,
        embeddings_path=args.embeddings_out,
        meta_path=args.meta_out,
        report_path=args.report_out,
        model_name=args.model,
        pretrained=args.pretrained,
        batch_size=args.batch_size,
        device=args.device,
        strict=args.strict,
        backup_old=not args.no_backup,
        legacy_root_copy=args.legacy_root_copy,
    )

    try:
        report = build_recipe_index(config)
    except Exception as e:
        logger.exception("Recipe index build failed: %s", e)
        return 1

    logger.info("Build completed.")
    logger.info(
        "Indexed recipes: %s/%s",
        report["validation"]["recipes_valid_for_index"],
        report["validation"]["recipes_total"],
    )
    logger.info("Warnings: %s", report["validation"]["total_warnings"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())