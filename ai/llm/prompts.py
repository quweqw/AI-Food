import json

def build_prompt(ingredients, preferences, restrictions, goal):
    ing_list = ", ".join(ingredients)
    ingredients_json = json.dumps(ingredients)

    return f"""
You are a strict food recognition system.

You MUST ONLY use the provided ingredients.
DO NOT invent new ingredients.
DO NOT add anything new.

Detected ingredients:
{ing_list}

Rules:
- Only use these ingredients
- If unsure, use a simple dish name like "shrimp noodles"
- Do NOT guess extra components

Return STRICT JSON:

{{
  "dish_name": "...",
  "ingredients": {ingredients_json},
  "calories": number,
  "protein": number,
  "fat": number,
  "carbs": number
}}
"""

def build_recipe_prompt(ingredients, user_profile):
    return f"""
You are a professional chef AI.

Use ONLY these ingredients:
{ingredients}

User goal: {user_profile.get("goal")}

Tasks:
1. Generate dish name
2. Generate cooking steps
3. Keep ingredients consistent
4. Optimize for user's goal

Return JSON:

{{
  "dish_name": "...",
  "steps": ["..."],
  "tips": "..."
}}
"""