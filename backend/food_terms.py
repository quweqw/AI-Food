from __future__ import annotations

import re
from typing import Any, Iterable, List, Set


_SPACE_RE = re.compile(r"[\s\-]+")


FOOD_ALIASES: dict[str, list[str]] = {
    "яйца": ["egg", "eggs", "яйцо", "яйца"],
    "яйцо": ["egg", "eggs", "яйцо", "яйца"],
    "egg": ["egg", "eggs", "яйцо", "яйца"],
    "eggs": ["egg", "eggs", "яйцо", "яйца"],
    "глютен": [
        "gluten",
        "wheat",
        "flour",
        "pastry_flour",
        "rye_flour",
        "sweet_rice_flour",
        "tortilla_flour",
        "wheat_flour_whole",
        "bread",
        "bread_white",
        "pita_bread",
        "rye_bread",
        "sourdough_bread",
        "pasta",
        "noodles",
        "макароны",
        "хлеб",
        "мука",
    ],
    "молоко": [
        "dairy",
        "milk",
        "milk_2_5",
        "buttermilk",
        "coconut_milk",
        "condensed_milk",
        "evaporated_milk",
        "ricotta_whole_milk",
        "cheese",
        "cheddar_cheese",
        "parmesan",
        "parmesan_cheese",
        "feta",
        "halloumi",
        "cottage_cheese",
        "cottage_cheese_5",
        "yogurt",
        "yogurt_natural_2",
        "greek_yogurt",
        "cream",
        "heavy_cream",
        "cream_cheese",
        "butter",
        "молоко",
        "сыр",
        "творог",
        "йогурт",
        "сливочное масло",
    ],
    "молочные продукты": [
        "dairy",
        "milk",
        "milk_2_5",
        "cheese",
        "cottage_cheese",
        "cottage_cheese_5",
        "yogurt",
        "yogurt_natural_2",
        "greek_yogurt",
        "cream",
        "heavy_cream",
        "cream_cheese",
        "butter",
    ],
    "арахис": ["peanut", "peanuts", "peanut_butter", "peanut_sauce", "арахис"],
    "орехи": ["nuts", "walnuts", "almond", "almond_milk", "орехи", "грецкие орехи", "миндаль"],
    "соя": ["soy", "soy_sauce", "soy_milk", "tofu", "tofu_firm", "tempeh", "соя", "тофу"],
    "рыба": ["fish", "fish_sauce", "fish_stock", "salmon", "tuna", "cod", "catfish", "рыба", "лосось", "тунец", "треска"],
    "морепродукты": ["seafood", "shellfish", "shrimp", "prawn", "crab", "lobster", "креветки", "краб"],
    "кунжут": ["sesame", "sesame_oil", "кунжут", "кунжутное масло"],
    "горчица": ["mustard", "горчица"],
    "курица": ["chicken", "chicken_broth", "курица"],
    "говядина": ["beef", "lean_beef", "ground_beef", "red_meat", "говядина"],
    "свинина": ["pork", "pork_tenderloin_lean", "свинина"],
    "лосось": ["salmon", "fish", "лосось"],
    "тунец": ["tuna", "fish", "тунец"],
    "творог": ["cottage_cheese", "cottage_cheese_5", "dairy", "творог"],
    "гречка": ["buckwheat", "гречка"],
    "рис": ["rice", "rice_noodles", "rice_paper", "рис"],
    "овсянка": ["oat", "oats", "rolled_oat", "oat_flakes_raw", "овсянка"],
    "картофель": ["potato", "sweet_potato", "картофель"],
    "брокколи": ["broccoli", "брокколи"],
    "морковь": ["carrot", "морковь"],
    "помидор": ["tomato", "tomatoes", "tomato_paste", "помидор", "томат"],
    "томат": ["tomato", "tomatoes", "tomato_paste", "помидор", "томат"],
    "огурец": ["cucumber", "огурец"],
    "банан": ["banana", "банан"],
    "яблоко": ["apple", "яблоко"],
    "апельсин": ["orange", "апельсин"],
    "авокадо": ["avocado", "авокадо"],
    "оливковое масло": ["olive_oil", "oil", "оливковое масло"],
    "сыр": ["cheese", "cheddar_cheese", "parmesan", "parmesan_cheese", "feta", "halloumi", "dairy", "сыр"],
    "йогурт": ["yogurt", "yogurt_natural_2", "greek_yogurt", "dairy", "йогурт"],
    "хлеб": ["bread", "bread_white", "pita_bread", "rye_bread", "sourdough_bread", "gluten", "хлеб"],
    "макароны": ["pasta", "noodles", "gluten", "макароны", "паста"],
    "паста": ["pasta", "noodles", "gluten", "макароны", "паста"],
    "чечевица": ["lentils_raw", "lentil", "red_lentil", "чечевица"],
    "нут": ["chickpeas", "chickpea", "нут"],
    "шпинат": ["spinach", "шпинат"],
    "перец": ["bell_pepper", "pepper", "перец"],
    "лук": ["onion", "green_onion", "лук"],
}


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ё", "е")
    text = _SPACE_RE.sub("_", text)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


_REVERSE_ALIASES: dict[str, list[str]] = {}
for _key, _values in FOOD_ALIASES.items():
    group = [_key, *_values]
    for _value in group:
        _REVERSE_ALIASES.setdefault(_normalize_token(_value), [])
        for _candidate in group:
            if _candidate not in _REVERSE_ALIASES[_normalize_token(_value)]:
                _REVERSE_ALIASES[_normalize_token(_value)].append(_candidate)


def expand_food_terms(values: Iterable[Any] | None) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()

    for value in values or []:
        raw = str(value or "").strip()
        if not raw:
            continue

        candidates = [raw]
        normalized = _normalize_token(raw)
        candidates.append(normalized)
        candidates.extend(_REVERSE_ALIASES.get(normalized, []))

        for candidate in candidates:
            candidate_text = str(candidate or "").strip()
            if not candidate_text:
                continue
            key = _normalize_token(candidate_text)
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate_text)

    return result


def forbidden_search_terms(values: Iterable[Any] | None) -> List[str]:
    terms: List[str] = []
    seen: Set[str] = set()
    for term in expand_food_terms(values):
        normalized = _normalize_token(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized.replace("_", " "))
    return terms
