from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from auth.service import decode_token
import json
import sys
import os
import asyncio
import re

# Добавляем корень проекта в путь
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from ai.llm.llm_service import FoodLLM
from ai.core.user_profile import UserProfile
try:
    from food_terms import expand_food_terms, forbidden_search_terms
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from backend.food_terms import expand_food_terms, forbidden_search_terms

router = APIRouter(prefix="/chat", tags=["chat"])
security = HTTPBearer()

# Загружаем один раз
_llm = None

def get_llm() -> FoodLLM:
    global _llm
    if _llm is None:
        _llm = FoodLLM()
    return _llm

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    email = decode_token(credentials.credentials)
    if not email:
        raise HTTPException(401, "Невалидный токен")
    return email

class ChatHistoryMessage(BaseModel):
    role: str = "user"
    content: str = ""


class ChatRequest(BaseModel):
    message: str
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    allergens: list[str] = []
    favorite_products: list[str] = []
    disliked_products: list[str] = []
    excluded_products: list[str] = []
    daily_calories: int = 2000
    diet_type: str = "normal"
    age: int = 25
    gender: str = "male"
    height: int = 175
    weight: float = 70.0

def _build_user_profile(data: ChatRequest) -> UserProfile:
    # Маппинг diet_type из Flutter в goal для ML
    goal_map = {
        "bulk": "muscle_gain",
        "cut": "weight_loss",
        "normal": "balanced",
    }
    return UserProfile(
        age=data.age,
        sex=data.gender,
        height_cm=data.height,
        weight_kg=data.weight,
        activity_level="moderate",
        allergies=expand_food_terms(data.allergens),
        preferred_ingredients=expand_food_terms(data.favorite_products),
        disliked_ingredients=expand_food_terms(data.disliked_products),
        excluded_ingredients=expand_food_terms(data.excluded_products),
        goal=goal_map.get(data.diet_type, "balanced"),
        target_calories=data.daily_calories,
    )

def _build_prompt(data: ChatRequest) -> str:
    goal_map = {
        "bulk": "массонабор",
        "cut": "сушка",
        "normal": "норма",
    }
    allergen_terms = expand_food_terms(data.allergens)
    excluded_terms = expand_food_terms(data.excluded_products)
    disliked_terms = expand_food_terms(data.disliked_products)
    favorite_terms = expand_food_terms(data.favorite_products)
    history_context = _build_history_context(data.history)
    history_block = (
        f"\nКонтекст текущего диалога:\n{history_context}\n"
        if history_context
        else "\nКонтекст текущего диалога: пока нет предыдущих сообщений.\n"
    )

    return f"""Ты AI Food — персональный помощник по питанию. Отвечай на языке сообщений от пользователя.

Параметры пользователя:
- Возраст: {data.age}, Пол: {data.gender}
- Рост: {data.height} см, Вес: {data.weight} кг
- Калорий в день: {data.daily_calories}
- Цель: {goal_map.get(data.diet_type, "норма")}
- Аллергены: {', '.join(data.allergens) if data.allergens else 'нет'}
- Исключить: {', '.join(data.excluded_products) if data.excluded_products else 'нет'}
- Нелюбимые продукты: {', '.join(data.disliked_products) if data.disliked_products else 'нет'}
- Любимые продукты: {', '.join(data.favorite_products) if data.favorite_products else 'нет'}

Жесткие ограничения:
- Не предлагай и не добавляй в рецепты аллергены: {', '.join(allergen_terms) if allergen_terms else 'нет'}.
- Не предлагай исключенные продукты: {', '.join(excluded_terms) if excluded_terms else 'нет'}.
- Нелюбимые продукты можно упоминать только как нежелательные: {', '.join(disliked_terms) if disliked_terms else 'нет'}.
- Любимые продукты можно учитывать как предпочтения: {', '.join(favorite_terms) if favorite_terms else 'нет'}.

Отвечай конкретно, по делу, на русском языке. Все названия блюд, ингредиенты и инструкции пиши по-русски.
Если пользователь уточняет прошлый ответ, спрашивает про “твой рецепт”, “выше”, “эту порцию” или “предложенное блюдо”, обязательно используй контекст диалога и отвечай именно на уточнение. Не подменяй уточняющий вопрос новым списком рецептов.
{history_block}
Текущий вопрос пользователя: {data.message}"""


def _build_history_context(history: list[ChatHistoryMessage]) -> str:
    lines: list[str] = []
    for item in history[-12:]:
        content = " ".join(str(item.content or "").split())
        if not content:
            continue
        if len(content) > 1200:
            content = content[:1200] + "..."
        role = "Пользователь" if item.role == "user" else "AI Food"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _mentions_forbidden_food(text: str, data: ChatRequest) -> bool:
    haystack = " " + re.sub(
        r"[^0-9a-zа-яё]+",
        " ",
        str(text or "").lower().replace("_", " "),
    ) + " "
    for term in forbidden_search_terms([*data.allergens, *data.excluded_products]):
        if not term or len(term) < 3:
            continue
        if f" {term.lower()} " in haystack:
            return True
    return False

@router.post("/stream")
async def chat_stream(
    data: ChatRequest,
    user_email: str = Depends(get_current_user)
):
    async def generate():
        try:
            llm = get_llm()
            prompt = _build_prompt(data)
            response = llm.generate_chat(prompt)

            if not response:
                yield f"data: {json.dumps({'text': 'Не удалось получить ответ. Проверь что Ollama запущена.'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Стримим посимвольно
            for char in response:
                yield f"data: {json.dumps({'text': char})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'text': f'Ошибка: {str(e)}'})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@router.post("/message")
async def chat_message(
    data: ChatRequest,
    user_email: str = Depends(get_current_user)
):
    try:
        llm = get_llm()
        prompt = _build_prompt(data)
        response = llm.generate_chat(prompt)
        if _mentions_forbidden_food(response, data):
            retry_prompt = (
                prompt
                + "\n\nПредыдущий ответ содержал запрещенный продукт. "
                "Перепиши ответ полностью, исключив аллергены и запрещенные продукты."
            )
            response = llm.generate_chat(retry_prompt)
            if _mentions_forbidden_food(response, data):
                response = (
                    "Я не могу безопасно предложить этот вариант: в ответе появился продукт "
                    "из ваших аллергенов или исключений. Уточните запрос, и я подберу безопасную альтернативу."
                )

        if not response:
            raise HTTPException(500, "Ollama не отвечает — проверь что запущена")

        return {"response": response}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))
