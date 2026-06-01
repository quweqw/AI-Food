from __future__ import annotations

import ast
import json
import re
from copy import deepcopy
from typing import Any, Dict, List


CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")


RECIPE_TITLE_TRANSLATIONS = {
    "baked cod tacos": "Тако с запеченной треской",
    "beef bulgur pilaf": "Плов из булгура с говядиной",
    "beef empanadas": "Эмпанадас с говядиной",
    "beef rice noodle bowl": "Боул с говядиной и рисовой лапшой",
    "chicken buckwheat bowl": "Боул с курицей и гречкой",
    "chicken couscous bowl": "Боул с курицей и кускусом",
    "chicken fajita bowl": "Боул с куриной фахитой",
    "chicken pot pie": "Куриный пирог в горшочке",
    "chicken rice bowl": "Боул с курицей и рисом",
    "chicken tikka masala": "Курица тикка масала",
    "chicken vegetable soup": "Овощной суп с курицей",
    "cod with potatoes and green beans": "Треска с картофелем и зеленой фасолью",
    "egg fried buckwheat": "Гречка с жареным яйцом",
    "egg salad bowl": "Боул с яичным салатом",
    "hünkar beğendi": "Хюнкар бегенди",
    "lean pork rice bowl": "Боул с рисом и нежирной свининой",
    "nalisniki": "Налистники",
    "pad thai": "Пад тай",
    "pasta e fagioli": "Паста э фасоли",
    "pho bo (vietnamese beef noodle soup)": "Фо бо, вьетнамский суп с говядиной и лапшой",
    "tuna pasta bake": "Запеканка из пасты с тунцом",
    "tuna salad sandwich": "Сэндвич с салатом из тунца",
    "turkey bolognese": "Болоньезе с индейкой",
    "turkey chili": "Чили с индейкой",
    "turkey egg breakfast wrap": "Завтрак-ролл с индейкой и яйцом",
    "turkey lettuce wraps": "Листья салата с индейкой",
    "vareniki": "Вареники",
    "vegetable stir fry": "Овощной стир-фрай",
    "zucchini fritters": "Оладьи из цукини",
    "shrimp rice paper rolls": "Роллы из рисовой бумаги с креветками",
    "chicken pesto pasta light": "Лёгкая паста с курицей и песто",
    "chicken pesto pasta": "Паста с курицей и песто",
}


FOOD_TRANSLATIONS = {
    "anchovy": "анчоус",
    "anchovy_canned_oil": "анчоус в масле",
    "beef": "говядина",
    "bell pepper": "болгарский перец",
    "bell_pepper": "болгарский перец",
    "bread": "хлеб",
    "bread_white": "белый хлеб",
    "buckwheat": "гречка",
    "bulgur": "булгур",
    "butter": "сливочное масло",
    "cabbage": "капуста",
    "carrot": "морковь",
    "cheddar_cheese": "сыр чеддер",
    "cheese": "сыр",
    "chicken": "курица",
    "club_soda": "газированная вода",
    "cod": "треска",
    "corn": "кукуруза",
    "cottage_cheese": "творог",
    "cottage_cheese_5": "творог 5%",
    "couscous": "кускус",
    "croutons": "крутоны",
    "cumin": "зира",
    "egg": "яйцо",
    "egg wash": "яичная смазка",
    "feta": "фета",
    "flour": "мука",
    "garlic": "чеснок",
    "green beans": "зеленая фасоль",
    "green olives": "зеленые оливки",
    "ground beef": "говяжий фарш",
    "lamb": "баранина",
    "lemon": "лимон",
    "legumes": "бобовые",
    "lettuce": "салат",
    "mayonnaise": "майонез",
    "mint": "мята",
    "noodles": "лапша",
    "olive_oil": "оливковое масло",
    "olives": "оливки",
    "onion": "лук",
    "oregano": "орегано",
    "oregano_dried": "сушеный орегано",
    "pancetta": "панчетта",
    "paprika": "паприка",
    "paper": "рисовая бумага",
    "parmesan": "пармезан",
    "parmesan cheese": "сыр пармезан",
    "parmesan_cheese": "сыр пармезан",
    "pasta": "паста",
    "peanut": "арахис",
    "peanut_butter": "арахисовое масло",
    "peanut sauce": "арахисовый соус",
    "peanut_sauce": "арахисовый соус",
    "pepper": "перец",
    "pesto": "песто",
    "pork": "свинина",
    "potato": "картофель",
    "rice": "рис",
    "rice paper": "рисовая бумага",
    "rice_paper": "рисовая бумага",
    "rice paper sheets": "листы рисовой бумаги",
    "rice_paper_sheets": "листы рисовой бумаги",
    "rice noodles": "рисовая лапша",
    "romaine lettuce": "салат ромэн",
    "salt": "соль",
    "shrimp": "креветки",
    "tofu": "тофу",
    "tomato": "помидор",
    "tomatoes": "помидоры",
    "tuna": "тунец",
    "turkey": "индейка",
    "vinegar": "уксус",
    "water": "вода",
    "zucchini": "цукини",
    "basil": "базилик",
    "cucumber": "огурец",
    "cilantro": "кинза",
    "dish": "блюдо",
}


WORD_TRANSLATIONS = {
    "add": "добавьте",
    "basil": "базилик",
    "bake": "запекайте",
    "beef": "говядина",
    "boil": "варите",
    "brown": "обжарьте",
    "brush": "смажьте",
    "butter": "сливочное масло",
    "chicken": "курица",
    "cilantro": "кинза",
    "chill": "охладите",
    "chopped": "нарезанный",
    "cold": "холодный",
    "cook": "готовьте",
    "cut": "нарежьте",
    "diced": "нарезанный кубиками",
    "dough": "тесто",
    "drain": "слейте",
    "egg": "яйцо",
    "filling": "начинка",
    "fill": "начините",
    "flour": "мука",
    "fold": "сложите",
    "golden": "золотистого цвета",
    "knead": "замесите",
    "light": "лёгкая",
    "meat": "мясо",
    "mint": "мята",
    "mix": "смешайте",
    "mixture": "смесь",
    "onion": "лук",
    "pastry": "тесто",
    "pepper": "перец",
    "pesto": "песто",
    "reserve": "сохраните",
    "rolls": "роллы",
    "roll": "раскатайте",
    "salt": "соль",
    "seal": "защипните",
    "serve": "подавайте",
    "sheets": "листы",
    "sauce": "соус",
    "saute": "обжарьте",
    "sauté": "обжарьте",
    "soften": "размочите",
    "stir": "перемешайте",
    "thin": "тонко",
    "then": "затем",
    "tightly": "плотно",
    "tomatoes": "помидоры",
    "toss": "смешайте",
    "vinegar": "уксус",
    "warm": "теплым",
    "water": "вода",
    "dish": "блюдо",
}


EXACT_INSTRUCTION_TRANSLATIONS = {
    "Make pastry: cut 1/2 cup cold butter into 2.5 cups flour with salt.": (
        "Приготовьте тесто: порубите 1/2 стакана холодного сливочного масла "
        "с 2,5 стаканами муки и солью."
    ),
    "Mix 1 egg, 1/3 cup cold water, 1 tbsp vinegar, add to flour mixture, knead briefly.": (
        "Смешайте 1 яйцо, 1/3 стакана холодной воды и 1 ст. л. уксуса, "
        "добавьте к мучной смеси и быстро замесите тесто."
    ),
    "Chill 1 hour.": "Охладите 1 час.",
    "For filling: brown 500g ground beef with 1 chopped onion, 1 diced bell pepper.": (
        "Для начинки обжарьте 500 г говяжьего фарша с 1 нарезанной луковицей "
        "и 1 болгарским перцем, нарезанным кубиками."
    ),
    "Drain fat.": "Слейте лишний жир.",
    "Add 2 tsp cumin, 1 tsp paprika, 1 tsp oregano, salt, pepper.": (
        "Добавьте 2 ч. л. зиры, 1 ч. л. паприки, 1 ч. л. орегано, соль и перец."
    ),
    "Stir in 1/4 cup chopped green olives and 1 chopped hard-boiled egg.": (
        "Вмешайте 1/4 стакана нарезанных зеленых оливок и 1 нарезанное вареное яйцо."
    ),
    "Roll dough thin, cut circles.": "Тонко раскатайте тесто и вырежьте круги.",
    "Fill with meat mixture, fold over, seal with fork.": (
        "Выложите мясную начинку, сложите тесто пополам и защипните края вилкой."
    ),
    "Brush with egg wash.": "Смажьте яйцом.",
    "Bake at 200°C (400°F) 20-25 min until golden.": (
        "Запекайте при 200°C (400°F) 20-25 минут до золотистого цвета."
    ),
    "Bake at 200В°C (400В°F) 20-25 min until golden.": (
        "Запекайте при 200°C (400°F) 20-25 минут до золотистого цвета."
    ),
    "Serve warm or room temp.": "Подавайте теплым или комнатной температуры.",
    "Soften rice paper sheets.": "Размочите листы рисовой бумаги.",
    "Fill with shrimp, noodles, lettuce, cucumber, carrot and mint.": (
        "Наполните креветками, лапшой, салатом, огурцом, морковью и мятой."
    ),
    "Roll tightly and serve with peanut sauce.": (
        "Плотно сверните и подавайте с арахисовым соусом."
    ),
    "Cook pasta and reserve water.": "Отварите пасту и сохраните немного воды.",
    "Sauté chicken and zucchini, then toss with pasta, tomatoes, pesto and parmesan.": (
        "Обжарьте курицу и цукини, затем смешайте с пастой, помидорами, песто и пармезаном."
    ),
    "Saute chicken and zucchini, then toss with pasta, tomatoes, pesto and parmesan.": (
        "Обжарьте курицу и цукини, затем смешайте с пастой, помидорами, песто и пармезаном."
    ),
}


PHRASE_TRANSLATIONS = [
    (r"\bmake pastry:\b", "приготовьте тесто:"),
    (r"\bfor filling:\b", "для начинки:"),
    (r"\buntil golden\b", "до золотистого цвета"),
    (r"\broom temp\b", "комнатной температуры"),
    (r"\bhard-boiled egg\b", "вареное яйцо"),
    (r"\begg wash\b", "яичной смазкой"),
    (r"\bground beef\b", "говяжий фарш"),
    (r"\bbell pepper\b", "болгарский перец"),
    (r"\bolive oil\b", "оливковое масло"),
    (r"\bgreen olives\b", "зеленые оливки"),
    (r"\brice paper sheets\b", "листы рисовой бумаги"),
    (r"\brice paper\b", "рисовая бумага"),
    (r"\bpeanut sauce\b", "арахисовый соус"),
    (r"\breserve water\b", "сохраните немного воды"),
    (r"\bchopped\b", "нарезанный"),
    (r"\bdiced\b", "нарезанный кубиками"),
    (r"\bbriefly\b", "быстро"),
    (r"\bthen\b", "затем"),
    (r"\btightly\b", "плотно"),
    (r"\bwith\b", "с"),
    (r"\binto\b", "в"),
    (r"\bto\b", "к"),
    (r"\bin\b", "в"),
    (r"\band\b", "и"),
]


def localize_title(value: Any) -> str:
    text = _clean_text(str(value or "Блюдо"))
    if _has_cyrillic(text) and not _has_latin(text):
        return text

    lowered = text.lower()
    if "paper rolls" in lowered and ("shrimp" in lowered or "кревет" in lowered):
        return "Роллы из рисовой бумаги с креветками"
    if "pesto" in lowered and ("pasta" in lowered or "паста" in lowered) and ("chicken" in lowered or "куриц" in lowered):
        return "Лёгкая паста с курицей и песто" if "light" in lowered else "Паста с курицей и песто"
    if lowered.endswith(" dish"):
        raw_parts = re.split(r",|\band\b", text[:-5])
        translated_parts = [
            localize_food_name(part.strip())
            for part in raw_parts
            if part.strip()
        ]
        if translated_parts:
            result = ", ".join(translated_parts)
            return result[:1].upper() + result[1:]

    exact = RECIPE_TITLE_TRANSLATIONS.get(text.lower())
    if exact:
        return exact

    words = re.split(r"(\W+)", text)
    translated = [
        FOOD_TRANSLATIONS.get(part.lower().replace(" ", "_"), WORD_TRANSLATIONS.get(part.lower(), part))
        for part in words
    ]
    result = "".join(translated).strip()
    return result[:1].upper() + result[1:] if result else text


def localize_meal_type(value: Any) -> str:
    return {
        "breakfast": "завтрак",
        "lunch": "обед",
        "dinner": "ужин",
        "snack": "перекус",
        "snack2": "перекус",
        "meal": "прием пищи",
    }.get(str(value or "").lower(), str(value or "прием пищи"))


def localize_food_name(value: Any) -> str:
    text = _clean_text(str(value or ""))
    if not text:
        return text
    if _has_cyrillic(text) and not _has_latin(text):
        return text
    lowered = text.lower()
    if "peanut" in lowered and ("butter" in lowered or "масло" in lowered):
        return "арахисовое масло"
    if "peanut" in lowered and "sauce" in lowered:
        return "арахисовый соус"
    key = text.lower().strip().replace("-", "_")
    underscored = key.replace(" ", "_")
    return FOOD_TRANSLATIONS.get(key) or FOOD_TRANSLATIONS.get(underscored) or _translate_words(text)


def localize_ingredients(value: List[Any]) -> List[Any]:
    result = []
    for item in value or []:
        if isinstance(item, dict):
            translated = deepcopy(item)
            for key in ("name", "ingredient", "food"):
                if translated.get(key):
                    translated[key] = localize_food_name(translated[key])
            result.append(translated)
        elif isinstance(item, str):
            result.append(localize_food_name(item))
        else:
            result.append(item)
    return result


def parse_instruction_lines(value: Any) -> List[str]:
    parsed = _parse_serialized(value)

    if isinstance(parsed, list):
        return [
            text
            for item in parsed
            for text in parse_instruction_lines(item)
            if text
        ]

    if isinstance(parsed, dict):
        for key in ("text", "instruction", "description", "body"):
            if parsed.get(key):
                return parse_instruction_lines(parsed[key])
        if isinstance(parsed.get("steps"), list):
            return parse_instruction_lines(parsed["steps"])
        return []

    if isinstance(parsed, str):
        text = _clean_text(parsed)
        if not text:
            return []
        reparsed = _parse_serialized(text)
        if reparsed is not text:
            return parse_instruction_lines(reparsed)
        return [text]

    return []


def localize_instruction(value: Any) -> str:
    text = _clean_text(str(value or ""))
    if not text:
        return text
    if _has_cyrillic(text) and not _has_latin(text):
        return text
    lowered = text.lower()
    if "soften" in lowered and "paper" in lowered and "sheet" in lowered:
        return "Размочите листы рисовой бумаги."
    if "fill" in lowered and ("shrimp" in lowered or "кревет" in lowered) and ("mint" in lowered or "мят" in lowered):
        return "Наполните креветками, лапшой, салатом, огурцом, морковью и мятой."
    if "roll" in lowered and ("peanut" in lowered or "арахис" in lowered):
        return "Плотно сверните и подавайте с арахисовым соусом."
    if ("reserve" in lowered and "вод" in lowered) and ("pasta" in lowered or "паста" in lowered):
        return "Отварите пасту и сохраните немного воды."
    if ("toss" in lowered and "pesto" in lowered) and ("chicken" in lowered or "куриц" in lowered):
        return "Обжарьте курицу и цукини, затем смешайте с пастой, помидорами, песто и пармезаном."

    exact = EXACT_INSTRUCTION_TRANSLATIONS.get(text)
    if exact:
        return exact

    translated = text
    for pattern, replacement in PHRASE_TRANSLATIONS:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)

    translated = _replace_units(translated)
    translated = _translate_words(translated)
    return _capitalize_sentence(translated)


def _parse_serialized(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return text
    if not (
        (text.startswith("{") and text.endswith("}"))
        or (text.startswith("[") and text.endswith("]"))
    ):
        return text

    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return text


def _replace_units(text: str) -> str:
    replacements = [
        (r"\bcups\b", "стакана"),
        (r"\bcup\b", "стакана"),
        (r"\btbsp\b", "ст. л."),
        (r"\btsp\b", "ч. л."),
        (r"\bminutes\b", "минут"),
        (r"\bminute\b", "минута"),
        (r"\bmins\b", "мин"),
        (r"\bmin\b", "мин"),
        (r"\bhours\b", "часа"),
        (r"\bhour\b", "час"),
        (r"(\d)\s*g\b", r"\1 г"),
    ]
    result = text
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _translate_words(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        return WORD_TRANSLATIONS.get(word.lower(), FOOD_TRANSLATIONS.get(word.lower(), word))

    return re.sub(r"[A-Za-z_]+", replace, text)


def _clean_text(value: str) -> str:
    return (
        value.replace("В°", "°")
        .replace("Â°", "°")
        .replace("_", " ")
        .strip()
    )


def _capitalize_sentence(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text[:1].upper() + text[1:] if text else text


def _has_cyrillic(value: str) -> bool:
    return bool(CYRILLIC_RE.search(value))


def _has_latin(value: str) -> bool:
    return bool(LATIN_RE.search(value))
