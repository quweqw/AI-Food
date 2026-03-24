class MealBuilder:
    def build_meal(self, ingredients):
        """
        Простая генерация названия блюда
        """
        if not ingredients:
            return "unknown meal"

        return " ".join(ingredients[:2])

    def detect_cuisine(self, ingredients):
        """
        Простая эвристика кухни
        """
        ingredients = [i.lower() for i in ingredients]

        if any(i in ingredients for i in ["soy sauce", "noodles", "rice"]):
            return "asian"

        if any(i in ingredients for i in ["pasta", "tomato", "cheese"]):
            return "italian"

        if any(i in ingredients for i in ["beef", "bun"]):
            return "american"

        return "unknown"