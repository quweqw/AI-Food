from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from meal_planner.schemas import IntentParseResponse


GOAL_PATTERNS = {
    "weight_loss": (
        "похуд",
        "сушк",
        "дефицит",
        "weight loss",
        "lose weight",
        "cut",
    ),
    "muscle_gain": (
        "массо",
        "набор",
        "мышц",
        "bulk",
        "muscle",
    ),
    "balanced": (
        "баланс",
        "поддерж",
        "норм",
        "balanced",
        "maintenance",
    ),
}

MEAL_TYPES = {
    "breakfast": ("завтрак", "breakfast"),
    "lunch": ("обед", "lunch"),
    "dinner": ("ужин", "dinner"),
    "snack": ("перекус", "snack"),
}

NUMBER_WORDS = {
    "один": 1,
    "одного": 1,
    "одну": 1,
    "двое": 2,
    "двоих": 2,
    "двух": 2,
    "трое": 3,
    "троих": 3,
    "трех": 3,
    "трёх": 3,
    "четверо": 4,
    "четверых": 4,
    "четырех": 4,
    "четырёх": 4,
}

PLAN_REQUEST_PATTERNS = (
    "составь рацион",
    "сгенерируй рацион",
    "сделай рацион",
    "хочу рацион",
    "нужен рацион",
    "рацион на",
    "рацион до",
    "рацион для",
    "план питания",
    "меню на",
    "meal plan",
    "diet plan",
    "на неделю",
)

SUGGESTION_REQUEST_PATTERNS = (
    "что приготовить",
    "придумай",
    "подбери",
    "предложи",
    "сделай завтрак",
    "сделай обед",
    "сделай ужин",
    "составь завтрак",
    "составь обед",
    "составь ужин",
    "suggest",
)

CONTEXTUAL_QUESTION_PATTERNS = (
    "выше",
    "предложенн",
    "твоем рецепте",
    "твоём рецепте",
    "этом рецепте",
    "в рецепте",
    "этого блюда",
    "этой порции",
    "какой будет",
    "сколько",
    "по граммовкам",
    "грамм",
    "ответь на мой вопрос",
)

QUESTION_WORDS = (
    "какой",
    "какая",
    "какое",
    "какие",
    "сколько",
    "как",
    "почему",
    "зачем",
    "можно ли",
    "что значит",
    "ответь",
)


def parse_intent(
    message: str,
    current_profile: Optional[Dict[str, Any]] = None,
) -> IntentParseResponse:
    profile = current_profile or {}
    text = " ".join(str(message or "").lower().split())

    params: Dict[str, Any] = {}
    intent = "unknown"
    confidence = 0.0

    has_plan_request = _has_plan_request(text)
    has_suggestion_request = _has_suggestion_request(text)

    if _is_contextual_followup_question(text):
        return IntentParseResponse(intent="unknown", confidence=0.0)

    if has_plan_request:
        intent = "generate_meal_plan"
        confidence = 0.82

    if has_suggestion_request:
        intent = "suggest_dinner"
        confidence = max(confidence, 0.78)

    for meal_type, needles in MEAL_TYPES.items():
        if _has_any(text, needles):
            params["meal_type"] = meal_type
            if intent == "unknown" and has_suggestion_request:
                intent = "suggest_dinner"
                confidence = 0.74

    if intent == "suggest_dinner" and "meal_type" not in params:
        params["meal_type"] = "dinner"

    calories = _extract_calories(text)
    if calories:
        params["target_calories"] = calories
        if intent == "unknown":
            intent = "generate_meal_plan"
            confidence = 0.72

    days = _extract_days(text)
    if days:
        params["days"] = days
        if intent == "unknown":
            intent = "generate_meal_plan"
            confidence = 0.70
    elif intent == "generate_meal_plan" and _has_any(text, ("неделю", "week")):
        params["days"] = 7

    meals_per_day = _extract_meals_per_day(text)
    if meals_per_day:
        params["meals_per_day"] = meals_per_day

    servings = _extract_servings(text)
    if servings:
        params["servings"] = servings

    people_count = _extract_people_count(text)
    if people_count:
        params["people_count"] = people_count
        params.setdefault("servings", people_count)

    goal = _extract_goal(text)
    if goal:
        params["goal"] = goal
        if intent == "unknown":
            intent = "generate_meal_plan"
            confidence = 0.70

    ingredients = _extract_available_ingredients(text)
    if ingredients:
        params["ingredients_available"] = ingredients
        if intent == "unknown" and has_suggestion_request:
            intent = "suggest_dinner"
            confidence = 0.70

    excluded = _extract_excluded_ingredients(text)
    if excluded:
        params["excluded_ingredients"] = excluded
        if intent == "unknown":
            intent = "generate_meal_plan"
            confidence = 0.70

    allergies = _extract_allergies(text)
    if allergies:
        params["allergies"] = allergies
        if intent == "unknown":
            intent = "generate_meal_plan"
            confidence = 0.70

    if intent == "unknown":
        return IntentParseResponse(intent="unknown", confidence=0.0)

    if intent == "generate_meal_plan":
        params.setdefault("days", 7)
        params.setdefault("meals_per_day", int(profile.get("meals_per_day") or 3))

    requires_confirmation = _requires_confirmation(params, profile)
    actions = ["apply_once", "save_to_profile", "reject"] if requires_confirmation else []
    message_text = _confirmation_message(intent, params) if requires_confirmation else ""

    return IntentParseResponse(
        intent=intent,
        confidence=min(0.98, confidence),
        extracted_parameters=params,
        requires_confirmation=requires_confirmation,
        confirmation_message=message_text,
        actions=actions,
    )


def _has_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _has_plan_request(text: str) -> bool:
    if _has_any(text, PLAN_REQUEST_PATTERNS):
        return True
    return bool(
        re.search(
            r"\b(?:составь|сгенерируй|сделай|создай|подбери)\s+(?:мне\s+)?(?:рацион|меню|план\s+питания)\b",
            text,
        )
    )


def _has_suggestion_request(text: str) -> bool:
    if _has_any(text, SUGGESTION_REQUEST_PATTERNS):
        return True
    return bool(
        re.search(
            r"\b(?:приготовить|придумай|подбери|предложи|сделай|составь)\b.*\b(?:завтрак|обед|ужин|перекус)\b",
            text,
        )
    )


def _is_contextual_followup_question(text: str) -> bool:
    if _has_plan_request(text) or _has_suggestion_request(text):
        return False
    if not ("?" in text or _has_any(text, QUESTION_WORDS)):
        return False
    return _has_any(text, CONTEXTUAL_QUESTION_PATTERNS)


def _extract_calories(text: str) -> Optional[int]:
    match = re.search(r"(\d{3,4})\s*(?:ккал|калор|kcal|cal)", text)
    if not match:
        match = re.search(r"(?:до|на|around|about)\s*(\d{3,4})", text)
    if not match:
        return None
    value = int(match.group(1))
    return value if 900 <= value <= 5000 else None


def _extract_days(text: str) -> Optional[int]:
    match = re.search(r"(?:на|for)\s*(\d{1,2})\s*(?:дн|day)", text)
    if match:
        return max(1, min(14, int(match.group(1))))
    if "недел" in text or "week" in text:
        return 7
    return None


def _extract_meals_per_day(text: str) -> Optional[int]:
    match = re.search(r"(\d)\s*(?:при[её]м|раз[а]?\s+в\s+день|meals?)", text)
    if not match:
        return None
    return max(1, min(6, int(match.group(1))))


def _extract_servings(text: str) -> Optional[int]:
    match = re.search(r"(?:на|for)\s*(\d{1,2})\s*(?:порц|servings?)", text)
    if match:
        return max(1, min(20, int(match.group(1))))
    return None


def _extract_people_count(text: str) -> Optional[int]:
    match = re.search(r"(?:на|for)\s*(\d{1,2})\s*(?:человек|люд|people|persons?)", text)
    if match:
        return max(1, min(20, int(match.group(1))))
    for word, value in NUMBER_WORDS.items():
        if f"на {word}" in text:
            return value
    return None


def _extract_goal(text: str) -> Optional[str]:
    for goal, patterns in GOAL_PATTERNS.items():
        if _has_any(text, patterns):
            return goal
    return None


def _extract_available_ingredients(text: str) -> list[str]:
    match = re.search(r"(?:из|with)\s+(.+)$", text)
    if not match:
        return []
    raw = match.group(1)
    raw = re.split(r"[?.!]", raw)[0]
    parts = re.split(r",|\s+и\s+|\s+and\s+", raw)
    return [part.strip() for part in parts if 2 <= len(part.strip()) <= 40][:8]


def _extract_excluded_ingredients(text: str) -> list[str]:
    patterns = (
        r"(?:без|исключи|исключить|не добавляй|without|no)\s+(.+?)(?:$|[?.!,;])",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _split_ingredient_phrase(match.group(1))
    return []


def _extract_allergies(text: str) -> list[str]:
    patterns = (
        r"(?:аллергия на|аллерген[ы]?:?|allergy to)\s+(.+?)(?:$|[?.!,;])",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _split_ingredient_phrase(match.group(1))
    return []


def _split_ingredient_phrase(raw: str) -> list[str]:
    raw = re.sub(r"\b(?:пожалуйста|для рациона|в рационе|in the plan)\b", "", raw)
    parts = re.split(r",|\s+и\s+|\s+and\s+", raw)
    return [part.strip() for part in parts if 2 <= len(part.strip()) <= 40][:8]


def _requires_confirmation(params: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    profile_goal = _profile_goal(profile.get("goal") or profile.get("diet_type"))

    if "target_calories" in params and int(params["target_calories"]) != int(profile.get("target_calories") or profile.get("daily_calories") or 2000):
        return True
    if "goal" in params and params["goal"] != profile_goal:
        return True
    if "meals_per_day" in params and int(params["meals_per_day"]) != int(profile.get("meals_per_day") or 3):
        return True
    if params.get("excluded_ingredients") or params.get("allergies") or params.get("preferred_ingredients") or params.get("disliked_ingredients"):
        return True
    return False


def _profile_goal(value: Any) -> str:
    raw = str(value or "balanced").lower()
    if raw in {"cut", "weight_loss"}:
        return "weight_loss"
    if raw in {"bulk", "muscle_gain"}:
        return "muscle_gain"
    return "balanced"


def _confirmation_message(intent: str, params: Dict[str, Any]) -> str:
    if intent == "suggest_dinner":
        target = "ужин"
    else:
        target = f"рацион на {params.get('days', 7)} дней"

    parts = [target]
    if params.get("target_calories"):
        parts.append(f"до {params['target_calories']} ккал")
    if params.get("meals_per_day"):
        parts.append(f"{params['meals_per_day']} приема пищи")
    if params.get("goal") == "weight_loss":
        parts.append("для похудения")
    elif params.get("goal") == "muscle_gain":
        parts.append("для набора массы")
    if params.get("excluded_ingredients"):
        parts.append("без " + ", ".join(params["excluded_ingredients"]))
    if params.get("allergies"):
        parts.append("аллергии: " + ", ".join(params["allergies"]))

    return "Я понял: " + ", ".join(parts) + ". Как применить параметры?"
