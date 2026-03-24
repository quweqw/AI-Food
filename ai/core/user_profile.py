class UserProfile:
    def __init__(
        self,
        allergies=None,
        excluded_ingredients=None,
        preferred_ingredients=None,
        goal="balanced",
        recent_meals=None
    ):
        self.allergies = allergies or []
        self.excluded_ingredients = excluded_ingredients or []
        self.preferred_ingredients = preferred_ingredients or []
        self.goal = goal
        self.recent_meals = recent_meals or []