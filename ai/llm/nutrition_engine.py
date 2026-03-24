import json
from pathlib import Path

class NutritionEngine:
    def __init__(self):
        BASE_DIR = Path(__file__).resolve().parent
        db_path = BASE_DIR / "nutrition_db.json"

        if not db_path.exists():
            raise FileNotFoundError(f"nutrition_db.json not found: {db_path}")

        with open(db_path, "r", encoding="utf-8") as f:
            self.db = json.load(f)

    def calculate(self, ingredients):
        total = {
            "calories": 0,
            "protein": 0,
            "fat": 0,
            "carbs": 0
        }

        for ing in ingredients:
            if ing in self.db:
                data = self.db[ing]

                total["calories"] += data.get("calories", 0)
                total["protein"] += data.get("protein", 0)
                total["fat"] += data.get("fat", 0)
                total["carbs"] += data.get("carbs", 0)

        return total