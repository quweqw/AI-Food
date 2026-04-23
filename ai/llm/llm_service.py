import json
import logging
import requests

logger = logging.getLogger("FoodLLM")


class FoodLLM:
    def __init__(self, model="llama3.1:8b", base_url="http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    # ==============================
    # NORMALIZATION
    # ==============================

    def _fix_text(self, text):
        if not isinstance(text, str):
            return text
        try:
            return text.encode("latin1").decode("utf-8")
        except:
            return text


    def _deep_fix(self, obj):
        if isinstance(obj, dict):
            return {k: self._deep_fix(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_fix(v) for v in obj]
        elif isinstance(obj, str):
            return self._fix_text(obj)
        return obj


    def normalize(self, data):
        if not isinstance(data, dict):
            return data

        data = self._deep_fix(data)

        # унификация ключей
        if "good_points" in data:
            data["strengths"] = data.pop("good_points")

        if "benefits" in data:
            data["highlights"] = data.pop("benefits")

        if "quality_score" in data:
            data["score"] = data.pop("quality_score")

        # дефолты
        data.setdefault("score", 0)
        data.setdefault("issues", [])
        data.setdefault("strengths", [])

        return data

    def generate(self, prompt):
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a strict JSON generator. Output ONLY JSON. No explanations."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "options": {
                        "temperature": 0.0,
                        "top_p": 0.2,
                        "num_predict": 600
                    },
                    "stream": False
                },
                timeout=60
            )

            if response.status_code != 200:
                logger.error(f"Ollama HTTP error: {response.status_code} {response.text}")
                return ""

            data = response.json()
            return data.get("message", {}).get("content", "").strip()

        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            return ""

    def generate_json(self, prompt):
        response = self.generate(prompt)

        if not response:
            return {"error": "empty_response"}

        try:
            start = response.find("{")
            end = response.rfind("}")

            if start == -1 or end == -1 or end <= start:
                raise ValueError("No JSON object found")

            json_str = response[start:end + 1]
            parsed = json.loads(json_str)
            return self.normalize(parsed)

        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Raw response: {response}")
            return {"error": "invalid_json"}

    # ==============================
    # DISH GENERATION
    # ==============================
    def generate_dish(self, ingredients, goal=None):
        prompt = f"""
You are a professional nutrition AI.

STRICT RULES:
- Output ONLY JSON
- Dish must be realistic
- Use ONLY these ingredients (or compatible ones)
- Respect goal: {goal}
- DO NOT include:
  - shrimp (if replaced)
  - onion (or other disliked)
- Keep cuisine consistent
- Keep it simple

Ingredients:
{ingredients}

Return JSON:
{{
  "dish_name": "short clear dish name"
}}
"""

        result = self.generate_json(prompt)

        # fallback
        if "dish_name" not in result:
            return {"dish_name": " ".join(ingredients[:2])}

        return result

    # ==============================
    # RECIPE GENERATION
    # ==============================
    def generate_recipe(self, ingredients, goal=None):
        prompt = f"""
You are a professional chef and nutritionist.

STRICT RULES:
- Output ONLY JSON
- Keep recipe SIMPLE
- Respect goal: {goal}
- Avoid high-fat cooking if weight_loss
- DO NOT include forbidden ingredients
- Use mostly provided ingredients

Ingredients:
{ingredients}

Return JSON:
{{
  "steps": ["step 1", "step 2"],
  "tips": "short useful tip"
}}
"""

        result = self.generate_json(prompt)

        # fallback
        if "steps" not in result:
            return {
                "steps": ["Cook ingredients together simply."],
                "tips": "Keep it simple and healthy."
            }

        return result

    def explain_meal_plan(self, plan, user_profile):
        prompt = f"""
You are a premium nutrition coach.

Explain this meal plan in a user-friendly way.
Focus on why it fits the person's goal, calories, preferences, and restrictions.

Return STRICT JSON:
{{
  "summary": "...",
  "benefits": ["..."],
  "warnings": ["..."],
  "confidence": number,
  "daily_notes": [
    {{
      "day": 1,
      "note": "...",
      "why_it_fits": "..."
    }}
  ]
}}

Plan:
{json.dumps(plan, ensure_ascii=False)}
"""
        return self.generate_json(prompt)

    def review_meal_plan(self, plan, user_profile):
        prompt = f"""
You are a strict meal-plan auditor.

Check for:
- allergy problems
- excluded ingredients
- too much repetition
- poor calorie balance
- poor goal fit

Return STRICT JSON:
{{
  "safe": true/false,
  "score": number,
  "issues": ["..."],
  "good_points": ["..."]
}}

User:
{{
  "goal": "{getattr(user_profile, 'goal', None)}",
  "allergies": {json.dumps(getattr(user_profile, 'allergies', []), ensure_ascii=False)},
  "disliked_ingredients": {json.dumps(getattr(user_profile, 'disliked_ingredients', []), ensure_ascii=False)},
  "excluded_ingredients": {json.dumps(getattr(user_profile, 'excluded_ingredients', []), ensure_ascii=False)},
  "target_calories": {getattr(user_profile, 'target_calories', None)}
}}

Plan:
{json.dumps(plan, ensure_ascii=False)}
"""
        return self.generate_json(prompt)
