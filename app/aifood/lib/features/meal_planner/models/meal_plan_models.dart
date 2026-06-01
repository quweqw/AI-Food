import 'package:ai_food/core/providers/settings_provider.dart';

double _asDouble(dynamic value) {
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '') ?? 0.0;
}

int _asInt(dynamic value, [int fallback = 0]) {
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? fallback;
}

List<String> _asStringList(dynamic value) {
  if (value is List) {
    return value.map((item) => item.toString()).toList();
  }
  return const [];
}

List<dynamic> _asList(dynamic value) => value is List ? value : const [];

Map<String, dynamic> _asMap(dynamic value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return Map<String, dynamic>.from(value);
  return const {};
}

String goalForSettings(UserSettings settings) {
  switch (settings.dietType) {
    case DietType.cut:
      return 'weight_loss';
    case DietType.bulk:
      return 'muscle_gain';
    case DietType.normal:
      return 'balanced';
  }
}

String dietTypeForSettings(UserSettings settings) {
  switch (settings.dietType) {
    case DietType.cut:
      return 'cut';
    case DietType.bulk:
      return 'bulk';
    case DietType.normal:
      return 'normal';
  }
}

class MealNutrition {
  final double calories;
  final double protein;
  final double fat;
  final double carbs;

  const MealNutrition({
    this.calories = 0,
    this.protein = 0,
    this.fat = 0,
    this.carbs = 0,
  });

  factory MealNutrition.fromJson(dynamic json) {
    final data = _asMap(json);
    return MealNutrition(
      calories: _asDouble(data['calories']),
      protein: _asDouble(data['protein']),
      fat: _asDouble(data['fat']),
      carbs: _asDouble(data['carbs']),
    );
  }

  Map<String, dynamic> toJson() => {
        'calories': calories,
        'protein': protein,
        'fat': fat,
        'carbs': carbs,
      };
}

class MealProgress {
  final String status;
  final bool checked;
  final String? completedAt;
  final String userNote;

  const MealProgress({
    this.status = 'planned',
    this.checked = false,
    this.completedAt,
    this.userNote = '',
  });

  factory MealProgress.fromJson(dynamic json) {
    final data = _asMap(json);
    return MealProgress(
      status: data['status']?.toString() ?? 'planned',
      checked: data['checked'] == true,
      completedAt: data['completed_at']?.toString(),
      userNote: data['user_note']?.toString() ?? '',
    );
  }

  MealProgress copyWith({
    String? status,
    bool? checked,
    String? completedAt,
    String? userNote,
  }) {
    return MealProgress(
      status: status ?? this.status,
      checked: checked ?? this.checked,
      completedAt: completedAt ?? this.completedAt,
      userNote: userNote ?? this.userNote,
    );
  }

  Map<String, dynamic> toJson() => {
        'status': status,
        'checked': checked,
        'completed_at': completedAt,
        'user_note': userNote,
      };
}

class MealRecipe {
  final String id;
  final String name;
  final String? imageUrl;
  final List<dynamic> ingredients;
  final List<dynamic> ingredientsDetail;
  final List<String> instructions;
  final Map<String, dynamic> servingModel;
  final Map<String, dynamic> scaling;

  const MealRecipe({
    required this.id,
    required this.name,
    this.imageUrl,
    this.ingredients = const [],
    this.ingredientsDetail = const [],
    this.instructions = const [],
    this.servingModel = const {},
    this.scaling = const {},
  });

  factory MealRecipe.fromJson(dynamic json) {
    final data = _asMap(json);
    return MealRecipe(
      id: data['id']?.toString() ?? '',
      name: data['name']?.toString() ?? '',
      imageUrl: data['image_url']?.toString(),
      ingredients: _asList(data['ingredients']),
      ingredientsDetail: _asList(data['ingredients_detail']),
      instructions: _asStringList(data['instructions']),
      servingModel: _asMap(data['serving_model']),
      scaling: _asMap(data['scaling']),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'image_url': imageUrl,
        'ingredients': ingredients,
        'ingredients_detail': ingredientsDetail,
        'instructions': instructions,
        'serving_model': servingModel,
        'scaling': scaling,
      };
}

class MealPlanMeal {
  final String mealId;
  final int slot;
  final String mealType;
  final String name;
  final double score;
  final String tier;
  final int servings;
  final int servingsTotal;
  final int peopleCount;
  final double eatenWeightG;
  final double cookingTotalWeightG;
  final double userEatenWeightG;
  final MealNutrition nutrition;
  final MealNutrition nutritionTotal;
  final MealNutrition nutritionPerServing;
  final MealNutrition nutritionForUser;
  final String? mainCarb;
  final List<String> mainProteins;
  final MealRecipe recipe;
  final MealProgress progress;

  const MealPlanMeal({
    required this.mealId,
    required this.slot,
    required this.mealType,
    required this.name,
    this.score = 0,
    this.tier = 'normal',
    this.servings = 1,
    this.servingsTotal = 1,
    this.peopleCount = 1,
    this.eatenWeightG = 0,
    this.cookingTotalWeightG = 0,
    this.userEatenWeightG = 0,
    this.nutrition = const MealNutrition(),
    this.nutritionTotal = const MealNutrition(),
    this.nutritionPerServing = const MealNutrition(),
    this.nutritionForUser = const MealNutrition(),
    this.mainCarb,
    this.mainProteins = const [],
    required this.recipe,
    this.progress = const MealProgress(),
  });

  factory MealPlanMeal.fromJson(dynamic json) {
    final data = _asMap(json);
    return MealPlanMeal(
      mealId: data['meal_id']?.toString() ?? '',
      slot: _asInt(data['slot']),
      mealType: data['meal_type']?.toString() ?? 'meal',
      name: data['name']?.toString() ?? 'Meal',
      score: _asDouble(data['score']),
      tier: data['tier']?.toString() ?? 'normal',
      servings: _asInt(data['servings'], 1),
      servingsTotal: _asInt(data['servings_total'], 1),
      peopleCount: _asInt(data['people_count'], 1),
      eatenWeightG: _asDouble(data['eaten_weight_g']),
      cookingTotalWeightG: _asDouble(data['cooking_total_weight_g']),
      userEatenWeightG: _asDouble(data['user_eaten_weight_g']),
      nutrition: MealNutrition.fromJson(data['nutrition']),
      nutritionTotal: MealNutrition.fromJson(data['nutrition_total']),
      nutritionPerServing:
          MealNutrition.fromJson(data['nutrition_per_serving']),
      nutritionForUser: MealNutrition.fromJson(data['nutrition_for_user']),
      mainCarb: data['main_carb']?.toString(),
      mainProteins: _asStringList(data['main_proteins']),
      recipe: MealRecipe.fromJson(data['recipe']),
      progress: MealProgress.fromJson(data['progress']),
    );
  }

  MealPlanMeal copyWithProgress(MealProgress value) {
    return MealPlanMeal(
      mealId: mealId,
      slot: slot,
      mealType: mealType,
      name: name,
      score: score,
      tier: tier,
      servings: servings,
      servingsTotal: servingsTotal,
      peopleCount: peopleCount,
      eatenWeightG: eatenWeightG,
      cookingTotalWeightG: cookingTotalWeightG,
      userEatenWeightG: userEatenWeightG,
      nutrition: nutrition,
      nutritionTotal: nutritionTotal,
      nutritionPerServing: nutritionPerServing,
      nutritionForUser: nutritionForUser,
      mainCarb: mainCarb,
      mainProteins: mainProteins,
      recipe: recipe,
      progress: value,
    );
  }

  Map<String, dynamic> toJson() => {
        'meal_id': mealId,
        'slot': slot,
        'meal_type': mealType,
        'name': name,
        'score': score,
        'tier': tier,
        'servings': servings,
        'servings_total': servingsTotal,
        'people_count': peopleCount,
        'eaten_weight_g': eatenWeightG,
        'cooking_total_weight_g': cookingTotalWeightG,
        'user_eaten_weight_g': userEatenWeightG,
        'nutrition': nutrition.toJson(),
        'nutrition_total': nutritionTotal.toJson(),
        'nutrition_per_serving': nutritionPerServing.toJson(),
        'nutrition_for_user': nutritionForUser.toJson(),
        'main_carb': mainCarb,
        'main_proteins': mainProteins,
        'recipe': recipe.toJson(),
        'progress': progress.toJson(),
      };
}

class MealPlanDay {
  final int day;
  final double score;
  final double targetCalories;
  final double actualCalories;
  final MealNutrition macroSummary;
  final List<MealPlanMeal> meals;

  const MealPlanDay({
    required this.day,
    this.score = 0,
    this.targetCalories = 0,
    this.actualCalories = 0,
    this.macroSummary = const MealNutrition(),
    this.meals = const [],
  });

  factory MealPlanDay.fromJson(dynamic json) {
    final data = _asMap(json);
    return MealPlanDay(
      day: _asInt(data['day'], 1),
      score: _asDouble(data['score']),
      targetCalories: _asDouble(data['target_calories']),
      actualCalories: _asDouble(data['actual_calories']),
      macroSummary: MealNutrition.fromJson(data['macro_summary']),
      meals: _asList(data['meals']).map(MealPlanMeal.fromJson).toList(),
    );
  }

  MealPlanDay copyWithMeals(List<MealPlanMeal> value) {
    return MealPlanDay(
      day: day,
      score: score,
      targetCalories: targetCalories,
      actualCalories: actualCalories,
      macroSummary: macroSummary,
      meals: value,
    );
  }

  Map<String, dynamic> toJson() => {
        'day': day,
        'score': score,
        'target_calories': targetCalories,
        'actual_calories': actualCalories,
        'macro_summary': macroSummary.toJson(),
        'meals': meals.map((meal) => meal.toJson()).toList(),
      };
}

class PlanProgress {
  final String planId;
  final int daysTotal;
  final int daysCompleted;
  final int mealsTotal;
  final int mealsCompleted;
  final double completionPercent;
  final int currentDay;

  const PlanProgress({
    required this.planId,
    this.daysTotal = 0,
    this.daysCompleted = 0,
    this.mealsTotal = 0,
    this.mealsCompleted = 0,
    this.completionPercent = 0,
    this.currentDay = 1,
  });

  factory PlanProgress.fromJson(dynamic json) {
    final data = _asMap(json);
    return PlanProgress(
      planId: data['plan_id']?.toString() ?? '',
      daysTotal: _asInt(data['days_total']),
      daysCompleted: _asInt(data['days_completed']),
      mealsTotal: _asInt(data['meals_total']),
      mealsCompleted: _asInt(data['meals_completed']),
      completionPercent: _asDouble(data['completion_percent']),
      currentDay: _asInt(data['current_day'], 1),
    );
  }

  Map<String, dynamic> toJson() => {
        'plan_id': planId,
        'days_total': daysTotal,
        'days_completed': daysCompleted,
        'meals_total': mealsTotal,
        'meals_completed': mealsCompleted,
        'completion_percent': completionPercent,
        'current_day': currentDay,
      };
}

class MealPlanSummary {
  final int generatedMeals;
  final int emptySlots;
  final int normal;
  final int relaxed;
  final int emergency;
  final double avgCalorieError;
  final double avgProteinError;
  final double avgFatError;
  final double avgCarbsError;

  const MealPlanSummary({
    this.generatedMeals = 0,
    this.emptySlots = 0,
    this.normal = 0,
    this.relaxed = 0,
    this.emergency = 0,
    this.avgCalorieError = 0,
    this.avgProteinError = 0,
    this.avgFatError = 0,
    this.avgCarbsError = 0,
  });

  factory MealPlanSummary.fromJson(dynamic json) {
    final data = _asMap(json);
    return MealPlanSummary(
      generatedMeals: _asInt(data['generated_meals']),
      emptySlots: _asInt(data['empty_slots']),
      normal: _asInt(data['normal']),
      relaxed: _asInt(data['relaxed']),
      emergency: _asInt(data['emergency']),
      avgCalorieError: _asDouble(data['avg_calorie_error']),
      avgProteinError: _asDouble(data['avg_protein_error']),
      avgFatError: _asDouble(data['avg_fat_error']),
      avgCarbsError: _asDouble(data['avg_carbs_error']),
    );
  }

  Map<String, dynamic> toJson() => {
        'generated_meals': generatedMeals,
        'empty_slots': emptySlots,
        'normal': normal,
        'relaxed': relaxed,
        'emergency': emergency,
        'avg_calorie_error': avgCalorieError,
        'avg_protein_error': avgProteinError,
        'avg_fat_error': avgFatError,
        'avg_carbs_error': avgCarbsError,
      };
}

class MealPlan {
  final String planId;
  final List<MealPlanDay> days;
  final MealPlanSummary summary;
  final PlanProgress progress;
  final List<String> warnings;

  const MealPlan({
    required this.planId,
    this.days = const [],
    this.summary = const MealPlanSummary(),
    required this.progress,
    this.warnings = const [],
  });

  factory MealPlan.fromJson(dynamic json) {
    final data = _asMap(json);
    final planId = data['plan_id']?.toString() ?? '';
    return MealPlan(
      planId: planId,
      days: _asList(data['days']).map(MealPlanDay.fromJson).toList(),
      summary: MealPlanSummary.fromJson(data['summary']),
      progress: PlanProgress.fromJson(
        data['progress'] ?? {'plan_id': planId},
      ),
      warnings: _asStringList(data['warnings']),
    );
  }

  MealPlanMeal? findMeal(String mealId) {
    for (final day in days) {
      for (final meal in day.meals) {
        if (meal.mealId == mealId) return meal;
      }
    }
    return null;
  }

  MealPlan updateMealProgress(
    String mealId,
    MealProgress mealProgress,
    PlanProgress planProgress,
  ) {
    final updatedDays = days.map((day) {
      final meals = day.meals.map((meal) {
        return meal.mealId == mealId
            ? meal.copyWithProgress(mealProgress)
            : meal;
      }).toList();
      return day.copyWithMeals(meals);
    }).toList();

    return MealPlan(
      planId: planId,
      days: updatedDays,
      summary: summary,
      progress: planProgress,
      warnings: warnings,
    );
  }

  Map<String, dynamic> toJson() => {
        'plan_id': planId,
        'days': days.map((day) => day.toJson()).toList(),
        'summary': summary.toJson(),
        'progress': progress.toJson(),
        'warnings': warnings,
      };
}

class MealPlannerIntentResult {
  final String intent;
  final double confidence;
  final Map<String, dynamic> extractedParameters;
  final bool requiresConfirmation;
  final String confirmationMessage;
  final List<String> actions;

  const MealPlannerIntentResult({
    this.intent = 'unknown',
    this.confidence = 0,
    this.extractedParameters = const {},
    this.requiresConfirmation = false,
    this.confirmationMessage = '',
    this.actions = const [],
  });

  factory MealPlannerIntentResult.fromJson(dynamic json) {
    final data = _asMap(json);
    return MealPlannerIntentResult(
      intent: data['intent']?.toString() ?? 'unknown',
      confidence: _asDouble(data['confidence']),
      extractedParameters: _asMap(data['extracted_parameters']),
      requiresConfirmation: data['requires_confirmation'] == true,
      confirmationMessage: data['confirmation_message']?.toString() ?? '',
      actions: _asStringList(data['actions']),
    );
  }

  bool get isHighConfidence => intent != 'unknown' && confidence >= 0.70;
}

class MealPlannerChatResult {
  final bool handled;
  final String message;
  final bool openPlan;

  const MealPlannerChatResult({
    required this.handled,
    this.message = '',
    this.openPlan = false,
  });
}
