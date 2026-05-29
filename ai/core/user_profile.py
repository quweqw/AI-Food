# user_profile.py
from typing import List, Optional
from dataclasses import dataclass, field

# ──────────────────────────────────────────────
# КОНСТАНТЫ
# ──────────────────────────────────────────────

class GoalRate:
    # Скорость изменения веса в кг/неделю
    SLOW   = 0.25   # мягкий дефицит/профицит
    NORMAL = 0.5    # стандарт
    FAST   = 0.75   # агрессивный
    EXTREME = 1.0   # только под наблюдением

class TrainingType:
    STRENGTH  = "strength"   # силовые (3-5 раз/неделю)
    CARDIO    = "cardio"     # кардио доминирует
    MIXED     = "mixed"      # силовые + кардио
    LIGHT     = "light"      # прогулки, йога
    NONE      = "none"       # сидячий образ жизни

class EatingPattern:
    THREE_MEALS     = "3_meals"      # завтрак / обед / ужин
    FOUR_MEALS      = "4_meals"      # + перекус
    FIVE_MEALS      = "5_meals"      # спортивное питание
    IF_16_8         = "if_16_8"      # интервальное 16/8
    IF_18_6         = "if_18_6"      # интервальное 18/6
    TWO_MEALS       = "2_meals"      # только обед + ужин

class DietaryStyle:
    BALANCED    = "balanced"    # без ограничений
    LOW_CARB    = "low_carb"    # <100г углеводов/день
    KETO        = "keto"        # <50г углеводов/день
    HIGH_PROTEIN = "high_protein"  # >2г белка на кг
    VEGAN       = "vegan"       # без животных продуктов
    VEGETARIAN  = "vegetarian"  # без мяса
    PALEO       = "paleo"       # без злаков и молочки

class SatietyPreference:
    VOLUME    = "volume"    # большой объём, мало калорий
    BALANCED  = "balanced"  # стандарт
    DENSE     = "dense"     # малый объём, много калорий

# Маппинг EatingPattern → кол-во приёмов пищи и типы
EATING_PATTERN_MEALS = {
    EatingPattern.TWO_MEALS:   ["lunch", "dinner"],
    EatingPattern.THREE_MEALS: ["breakfast", "lunch", "dinner"],
    EatingPattern.FOUR_MEALS:  ["breakfast", "lunch", "snack", "dinner"],
    EatingPattern.FIVE_MEALS:  ["breakfast", "snack", "lunch", "snack2", "dinner"],
    EatingPattern.IF_16_8:     ["lunch", "snack", "dinner"],
    EatingPattern.IF_18_6:     ["lunch", "dinner"],
}

# Маппинг DietaryStyle → ограничения углеводов (г/день)
DIETARY_CARB_LIMITS = {
    DietaryStyle.KETO:       50,
    DietaryStyle.LOW_CARB:   100,
    DietaryStyle.BALANCED:   None,
    DietaryStyle.HIGH_PROTEIN: None,
    DietaryStyle.VEGAN:      None,
    DietaryStyle.VEGETARIAN: None,
    DietaryStyle.PALEO:      150,
}

# Маппинг DietaryStyle → исключённые группы продуктов
DIETARY_EXCLUDED_GROUPS = {
    DietaryStyle.VEGAN:      ["meat", "fish", "dairy", "eggs", "seafood"],
    DietaryStyle.VEGETARIAN: ["meat", "fish", "seafood"],
    DietaryStyle.PALEO:      ["grains", "dairy", "legumes"],
    DietaryStyle.KETO:       [],
    DietaryStyle.LOW_CARB:   [],
    DietaryStyle.BALANCED:   [],
    DietaryStyle.HIGH_PROTEIN: [],
}


# ──────────────────────────────────────────────
# USER PROFILE
# ──────────────────────────────────────────────

class UserProfile:
    def __init__(
        self,

        # ── Базовые параметры ──
        age:    Optional[int]   = None,
        sex:    str             = "male",
        height_cm: Optional[float] = None,
        weight_kg: Optional[float] = None,
        activity_level: str     = "moderate",

        # ── Цель ──
        goal:       Optional[str]   = None,       # bulk / cut / normal
        goal_rate:  float           = GoalRate.NORMAL,  # кг/неделю

        # ── Тренировки ──
        training_type:      str = TrainingType.NONE,
        training_days_per_week: int = 0,

        # ── Питание ──
        eating_pattern:     str = EatingPattern.THREE_MEALS,
        dietary_style:      str = DietaryStyle.BALANCED,
        satiety_preference: str = SatietyPreference.BALANCED,
        max_meal_size_kcal: Optional[int] = None,  # максимум ккал на 1 приём

        # ── Продукты ──
        allergies:              List[str] = None,
        disliked_ingredients:   List[str] = None,
        excluded_ingredients:   List[str] = None,
        preferred_ingredients:  List[str] = None,

        # ── История ──
        recent_meals:       List[dict] = None,
        allow_substitutions: bool = True,

        # ── Переопределения ──
        target_calories:    Optional[int] = None,  # если установлено вручную
        meals_per_day:      Optional[int] = None,  # если установлено вручную
    ):
        # Базовые
        self.age        = age
        self.sex        = sex
        self.height_cm  = height_cm
        self.weight_kg  = weight_kg
        self.activity_level = activity_level

        # Цель
        self.goal       = goal
        self.goal_rate  = goal_rate

        # Тренировки
        self.training_type          = training_type
        self.training_days_per_week = training_days_per_week

        # Питание
        self.eating_pattern     = eating_pattern
        self.dietary_style      = dietary_style
        self.satiety_preference = satiety_preference
        self.max_meal_size_kcal = max_meal_size_kcal

        # Продукты
        self.allergies             = allergies or []
        self.disliked_ingredients  = disliked_ingredients or []
        self.excluded_ingredients  = excluded_ingredients or []
        self.preferred_ingredients = preferred_ingredients or []

        # История
        self.recent_meals        = recent_meals or []
        self.allow_substitutions = allow_substitutions

        # Переопределения
        self._target_calories = target_calories
        self._meals_per_day   = meals_per_day

    # ──────────────────────────────────────────────
    # COMPUTED PROPERTIES
    # ──────────────────────────────────────────────

    @property
    def target_calories(self) -> int:
        # TDEE с поправкой на цель и скорость изменения веса
        if self._target_calories:
            return self._target_calories
        return self._calc_calories()

    @property
    def meals_per_day(self) -> int:
        if self._meals_per_day:
            return self._meals_per_day
        return len(self.meal_schedule)

    @property
    def meal_schedule(self) -> List[str]:
        # Список приёмов пищи согласно паттерну питания
        return EATING_PATTERN_MEALS.get(
            self.eating_pattern,
            ["breakfast", "lunch", "dinner"]
        )

    @property
    def carb_limit_g(self) -> Optional[int]:
        # Лимит углеводов из dietary style
        return DIETARY_CARB_LIMITS.get(self.dietary_style)

    @property
    def excluded_food_groups(self) -> List[str]:
        # Исключённые группы продуктов из dietary style
        return DIETARY_EXCLUDED_GROUPS.get(self.dietary_style, [])

    @property
    def protein_target_g(self) -> float:
        # Целевой белок в граммах.
        # Стандарт диетологии:
        # - Норма:       1.6 г/кг
        # - Массонабор:  1.8–2.2 г/кг
        # - Сушка:       2.2–2.5 г/кг (защита мышц)
        # - Силовые:     +0.2 г/кг
        
        if not self.weight_kg:
            return 120.0

        base_map = {
            "bulk":   2.0,
            "cut":    2.3,
            "normal": 1.6,
        }

        goal_key = self._normalize_goal()
        base = base_map.get(goal_key, 1.6)

        if self.training_type == TrainingType.STRENGTH:
            base += 0.2
        elif self.training_type == TrainingType.MIXED:
            base += 0.1

        if self.dietary_style == DietaryStyle.HIGH_PROTEIN:
            base = max(base, 2.2)

        return round(self.weight_kg * base, 1)

    @property
    def fat_target_g(self) -> float:
        #Целевые жиры. Минимум 0.8г/кг для гормонального здоровья
        #Keto: 70% калорий из жиров
        
        if not self.weight_kg:
            return 60.0

        if self.dietary_style == DietaryStyle.KETO:
            return round((self.target_calories * 0.70) / 9, 1)

        if self.dietary_style == DietaryStyle.LOW_CARB:
            return round((self.target_calories * 0.40) / 9, 1)

        # Стандарт: 25-30% калорий
        return round((self.target_calories * 0.27) / 9, 1)

    @property
    def max_meal_kcal(self) -> int:
        #Максимум калорий на один приём пищи
        if self.max_meal_size_kcal:
            return self.max_meal_size_kcal

        # Дефолт зависит от satiety preference
        if self.satiety_preference == SatietyPreference.VOLUME:
            return int(self.target_calories * 0.35)
        if self.satiety_preference == SatietyPreference.DENSE:
            return int(self.target_calories * 0.45)
        return int(self.target_calories * 0.40)

    # ──────────────────────────────────────────────
    # CALORIE CALCULATION
    # ──────────────────────────────────────────────

    def _normalize_goal(self) -> str:
        g = str(self.goal or "normal").lower()
        if g in ("bulk", "muscle_gain", "massonabor", "массонабор"):
            return "bulk"
        if g in ("cut", "weight_loss", "sushka", "сушка"):
            return "cut"
        return "normal"

    def _calc_calories(self) -> int:
        if None in (self.age, self.height_cm, self.weight_kg):
            return 2200

        # Mifflin-St Jeor — наиболее точная формула
        if self.sex == "male":
            bmr = 10 * self.weight_kg + 6.25 * self.height_cm - 5 * self.age + 5
        else:
            bmr = 10 * self.weight_kg + 6.25 * self.height_cm - 5 * self.age - 161

        # Activity multipliers (учитываем тренировки)
        activity_mult = {
            "sedentary": 1.2,
            "light":     1.375,
            "moderate":  1.55,
            "active":    1.725,
            "very_active": 1.9,
        }

        # Тренировочные дни добавляют к активности
        training_bonus = {
            TrainingType.NONE:     0,
            TrainingType.LIGHT:    0.05,
            TrainingType.CARDIO:   0.1,
            TrainingType.STRENGTH: 0.1,
            TrainingType.MIXED:    0.15,
        }

        act = activity_mult.get(self.activity_level, 1.55)
        act += training_bonus.get(self.training_type, 0)
        tdee = bmr * act

        # Поправка на цель + скорость
        # 1 кг жира ≈ 7700 ккал → в неделю → в день
        daily_adjustment = (self.goal_rate * 7700) / 7

        goal = self._normalize_goal()
        if goal == "cut":
            tdee -= daily_adjustment
        elif goal == "bulk":
            tdee += daily_adjustment

        # Минимальный безопасный порог
        min_calories = 1200 if self.sex == "female" else 1500
        return int(max(tdee, min_calories))

    # ──────────────────────────────────────────────
    # ИСТОРИЯ
    # ──────────────────────────────────────────────

    def add_meal(self, ingredients: List[str]):
        self.recent_meals.append({
            "ingredients": [i.lower() for i in ingredients]
        })
        if len(self.recent_meals) > 30:
            self.recent_meals.pop(0)

    def get_recent_ingredients(self) -> set:
        result = set()
        for meal in self.recent_meals:
            result.update(meal.get("ingredients", []))
        return result

    # ──────────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────────

    def summary(self) -> dict:
        #Краткий профиль для передачи в LLM / MealPlanner
        return {
            "age":              self.age,
            "sex":              self.sex,
            "weight_kg":        self.weight_kg,
            "height_cm":        self.height_cm,
            "goal":             self._normalize_goal(),
            "goal_rate_kg_week": self.goal_rate,
            "training_type":    self.training_type,
            "training_days":    self.training_days_per_week,
            "eating_pattern":   self.eating_pattern,
            "dietary_style":    self.dietary_style,
            "satiety":          self.satiety_preference,
            "target_calories":  self.target_calories,
            "protein_target_g": self.protein_target_g,
            "fat_target_g":     self.fat_target_g,
            "carb_limit_g":     self.carb_limit_g,
            "meal_schedule":    self.meal_schedule,
            "max_meal_kcal":    self.max_meal_kcal,
            "allergies":        self.allergies,
            "excluded_groups":  self.excluded_food_groups,
        }