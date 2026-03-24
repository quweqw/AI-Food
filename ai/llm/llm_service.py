import json
import re
import logging
import requests

logger = logging.getLogger("FoodLLM")


class FoodLLM:
    def __init__(self, model="llama3.1:8b", base_url="http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    # ==============================
    # RAW GENERATION (HTTP OLLAMA)
    # ==============================
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
                        "num_predict": 300
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

    # ==============================
    # SAFE JSON PARSER
    # ==============================
    def generate_json(self, prompt):
        response = self.generate(prompt)

        if not response:
            return {
                "error": "empty_response"
            }

        try:
            match = re.search(r"\{.*\}", response, re.DOTALL)

            if not match:
                raise ValueError("No JSON found")

            json_str = match.group()

            json_str = re.sub(r"(\d+)\s*g", r"\1", json_str)
            json_str = json_str.replace("\n", " ").replace("\t", " ")

            return json.loads(json_str)

        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Raw response: {response}")

            return {
                "error": "invalid_json"
            }

    # ==============================
    # DISH GENERATION
    # ==============================
    def generate_dish(self, ingredients, goal):
        prompt = f"""
Given ingredients: {ingredients}
Goal: {goal}

Return JSON:
{{
  "dish_name": "..."
}}
"""
        return self.generate_json(prompt)

    # ==============================
    # RECIPE GENERATION
    # ==============================
    def generate_recipe(self, ingredients, goal):
        prompt = f"""
Create a cooking recipe.

Ingredients: {ingredients}
Goal: {goal}

Return JSON:
{{
  "steps": ["..."],
  "tips": "..."
}}
"""
        return self.generate_json(prompt)