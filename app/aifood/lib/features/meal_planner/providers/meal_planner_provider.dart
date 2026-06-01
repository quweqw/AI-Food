import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ai_food/core/providers/settings_provider.dart';
import 'package:ai_food/core/services/api_service.dart';
import 'package:ai_food/features/meal_planner/models/meal_plan_models.dart';

enum MealPlannerStatus {
  idle,
  parsingIntent,
  waitingConfirmation,
  generatingPlan,
  planReady,
  error,
}

class MealPlannerState {
  final MealPlannerStatus status;
  final MealPlannerIntentResult? pendingIntent;
  final String pendingMessage;
  final MealPlan? currentPlan;
  final int selectedDay;
  final List<String> warnings;
  final String? error;

  const MealPlannerState({
    this.status = MealPlannerStatus.idle,
    this.pendingIntent,
    this.pendingMessage = '',
    this.currentPlan,
    this.selectedDay = 1,
    this.warnings = const [],
    this.error,
  });

  MealPlannerState copyWith({
    MealPlannerStatus? status,
    MealPlannerIntentResult? pendingIntent,
    bool clearPendingIntent = false,
    String? pendingMessage,
    MealPlan? currentPlan,
    int? selectedDay,
    List<String>? warnings,
    String? error,
    bool clearError = false,
  }) {
    return MealPlannerState(
      status: status ?? this.status,
      pendingIntent:
          clearPendingIntent ? null : pendingIntent ?? this.pendingIntent,
      pendingMessage: pendingMessage ?? this.pendingMessage,
      currentPlan: currentPlan ?? this.currentPlan,
      selectedDay: selectedDay ?? this.selectedDay,
      warnings: warnings ?? this.warnings,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class MealPlannerNotifier extends StateNotifier<MealPlannerState> {
  MealPlannerNotifier() : super(const MealPlannerState());

  Future<MealPlannerChatResult> tryHandleChatMessage(
    String message,
    UserSettings settings,
  ) async {
    state = state.copyWith(
      status: MealPlannerStatus.parsingIntent,
      clearError: true,
    );

    try {
      final intent = await apiService.parseMealPlannerIntent(message, settings);
      if (!intent.isHighConfidence) {
        state = state.copyWith(status: MealPlannerStatus.idle);
        return const MealPlannerChatResult(handled: false);
      }

      if (intent.requiresConfirmation) {
        state = state.copyWith(
          status: MealPlannerStatus.waitingConfirmation,
          pendingIntent: intent,
          pendingMessage: message,
        );
        return MealPlannerChatResult(
          handled: true,
          message: intent.confirmationMessage,
        );
      }

      return await _executeIntent(intent, settings, saveToProfile: false);
    } catch (_) {
      state = state.copyWith(status: MealPlannerStatus.idle);
      return const MealPlannerChatResult(handled: false);
    }
  }

  Future<MealPlannerChatResult> confirmPending(
    String action,
    UserSettings settings,
  ) async {
    final intent = state.pendingIntent;
    if (intent == null) {
      return const MealPlannerChatResult(
        handled: true,
        message: 'Нет ожидающего действия для рациона.',
      );
    }

    if (action == 'reject') {
      state = state.copyWith(
        status: MealPlannerStatus.idle,
        clearPendingIntent: true,
        pendingMessage: '',
      );
      return const MealPlannerChatResult(
        handled: true,
        message: 'Ок, ничего не меняю.',
      );
    }

    return _executeIntent(
      intent,
      settings,
      saveToProfile: action == 'save_to_profile',
    );
  }

  Future<void> loadLatestPlan() async {
    if (state.currentPlan != null) return;
    try {
      final plan = await apiService.getLatestMealPlan();
      state = state.copyWith(
        status: MealPlannerStatus.planReady,
        currentPlan: plan,
        selectedDay: plan.days.isNotEmpty ? plan.days.first.day : 1,
        warnings: plan.warnings,
        clearError: true,
      );
    } catch (_) {
      state = state.copyWith(status: MealPlannerStatus.idle);
    }
  }

  void selectDay(int day) {
    state = state.copyWith(selectedDay: day);
  }

  MealPlanMeal? mealById(String mealId) => state.currentPlan?.findMeal(mealId);

  Future<void> generateDefaultPlan(UserSettings settings) async {
    state = state.copyWith(
      status: MealPlannerStatus.generatingPlan,
      clearError: true,
    );

    try {
      final plan = await apiService.generateMealPlan({
        'days': 7,
        'meals_per_day': settings.mealsPerDay,
        'goal': goalForSettings(settings),
        'target_calories': settings.dailyCalories,
        'servings': 1,
        'people_count': 1,
        'portion_mode': 'single_user',
        'temporary_overrides': {
          'excluded': settings.excludedProducts,
          'preferred': settings.favoriteProducts,
          'disliked': settings.dislikedProducts,
          'allergies': settings.allergens,
        },
        'save_to_profile': false,
      });
      state = state.copyWith(
        status: MealPlannerStatus.planReady,
        currentPlan: plan,
        selectedDay: plan.days.isNotEmpty ? plan.days.first.day : 1,
        warnings: plan.warnings,
        clearError: true,
      );
    } catch (error) {
      state = state.copyWith(
        status: MealPlannerStatus.error,
        error: 'Не удалось создать рацион: $error',
      );
    }
  }

  Future<void> updateMealProgress(
    MealPlanMeal meal, {
    required String status,
    required bool checked,
    String? userNote,
  }) async {
    final plan = state.currentPlan;
    if (plan == null) return;

    final previous = plan;
    final optimisticMealProgress = meal.progress.copyWith(
      status: status,
      checked: checked,
      completedAt: checked ? DateTime.now().toIso8601String() : null,
      userNote: userNote,
    );
    final optimisticPlan = _withLocalProgress(
      plan,
      meal.mealId,
      optimisticMealProgress,
    );
    state = state.copyWith(
        currentPlan: optimisticPlan, warnings: optimisticPlan.warnings);

    try {
      final response = await apiService.updateMealProgress(
        planId: plan.planId,
        mealId: meal.mealId,
        progress: {
          'status': status,
          'checked': checked,
          if (userNote != null) 'user_note': userNote,
        },
      );
      final serverMealProgress =
          MealProgress.fromJson(response['meal_progress']);
      final serverPlanProgress =
          PlanProgress.fromJson(response['plan_progress']);
      state = state.copyWith(
        currentPlan: optimisticPlan.updateMealProgress(
          meal.mealId,
          serverMealProgress,
          serverPlanProgress,
        ),
        status: MealPlannerStatus.planReady,
        clearError: true,
      );
    } catch (error) {
      state = state.copyWith(
        currentPlan: previous,
        status: MealPlannerStatus.error,
        error: 'Не удалось обновить прогресс: $error',
      );
    }
  }

  Future<void> replaceMeal(MealPlanMeal meal) async {
    await _swapMeal(meal, regenerate: false);
  }

  Future<void> regenerateMeal(MealPlanMeal meal) async {
    await _swapMeal(meal, regenerate: true);
  }

  Future<void> _swapMeal(
    MealPlanMeal meal, {
    required bool regenerate,
  }) async {
    final plan = state.currentPlan;
    if (plan == null) return;

    state = state.copyWith(
      status: MealPlannerStatus.generatingPlan,
      clearError: true,
    );

    try {
      final updatedPlan = regenerate
          ? await apiService.regenerateMeal(
              planId: plan.planId,
              mealId: meal.mealId,
            )
          : await apiService.replaceMeal(
              planId: plan.planId,
              mealId: meal.mealId,
            );
      state = state.copyWith(
        status: MealPlannerStatus.planReady,
        currentPlan: updatedPlan,
        selectedDay: state.selectedDay,
        warnings: updatedPlan.warnings,
        clearError: true,
      );
    } catch (error) {
      state = state.copyWith(
        status: MealPlannerStatus.error,
        error: regenerate
            ? 'Не удалось пересобрать блюдо: $error'
            : 'Не удалось заменить блюдо: $error',
      );
    }
  }

  Future<MealPlannerChatResult> _executeIntent(
    MealPlannerIntentResult intent,
    UserSettings settings, {
    required bool saveToProfile,
  }) async {
    state = state.copyWith(
      status: MealPlannerStatus.generatingPlan,
      clearPendingIntent: true,
      pendingMessage: '',
      clearError: true,
    );

    try {
      if (intent.intent == 'generate_meal_plan') {
        final request = _generateRequest(intent, settings, saveToProfile);
        final plan = await apiService.generateMealPlan(request);
        state = state.copyWith(
          status: MealPlannerStatus.planReady,
          currentPlan: plan,
          selectedDay: plan.days.isNotEmpty ? plan.days.first.day : 1,
          warnings: plan.warnings,
          clearError: true,
        );
        return MealPlannerChatResult(
          handled: true,
          message: _planReadyMessage(plan, saveToProfile),
          openPlan: true,
        );
      }

      if (intent.intent == 'suggest_dinner') {
        if (saveToProfile) {
          await apiService
              .saveSettings(_settingsWithOverrides(settings, intent));
        }
        final suggestions = await apiService.suggestDinner(
          _suggestionRequest(intent, settings),
        );
        state = state.copyWith(status: MealPlannerStatus.idle);
        return MealPlannerChatResult(
          handled: true,
          message: _suggestionMessage(suggestions),
        );
      }

      state = state.copyWith(status: MealPlannerStatus.idle);
      return const MealPlannerChatResult(handled: false);
    } catch (error) {
      final text = 'Планировщик рациона не смог выполнить запрос: $error';
      state = state.copyWith(status: MealPlannerStatus.error, error: text);
      return MealPlannerChatResult(handled: true, message: text);
    }
  }

  Map<String, dynamic> _generateRequest(
    MealPlannerIntentResult intent,
    UserSettings settings,
    bool saveToProfile,
  ) {
    final params = intent.extractedParameters;
    final peopleCount = _intParam(params, 'people_count', 1);
    final servings = _intParam(
      params,
      'servings',
      peopleCount > 1 ? peopleCount : 1,
    );
    return {
      'days': _intParam(params, 'days', 7),
      'meals_per_day': _intParam(params, 'meals_per_day', settings.mealsPerDay),
      'goal': params['goal']?.toString() ?? goalForSettings(settings),
      'target_calories': _intParam(
        params,
        'target_calories',
        settings.dailyCalories,
      ),
      'servings': servings,
      'people_count': peopleCount,
      'portion_mode':
          servings > 1 || peopleCount > 1 ? 'cook_for_people' : 'single_user',
      'temporary_overrides': _temporaryOverrides(params),
      'save_to_profile': saveToProfile,
    };
  }

  Map<String, dynamic> _suggestionRequest(
    MealPlannerIntentResult intent,
    UserSettings settings,
  ) {
    final params = intent.extractedParameters;
    final peopleCount = _intParam(params, 'people_count', 1);
    final servings = _intParam(
      params,
      'servings',
      peopleCount > 1 ? peopleCount : 1,
    );
    return {
      'meal_type': params['meal_type']?.toString() ?? 'dinner',
      'target_calories': _intParam(params, 'target_calories', 600),
      'servings': servings,
      'people_count': peopleCount,
      'ingredients_available': params['ingredients_available'] ?? const [],
      'temporary_overrides': _temporaryOverrides(params),
    };
  }

  Map<String, dynamic> _temporaryOverrides(Map<String, dynamic> params) {
    return {
      if (params['target_calories'] != null)
        'target_calories': _intParam(params, 'target_calories', 0),
      if (params['goal'] != null) 'goal': params['goal'],
      if (params['meals_per_day'] != null)
        'meals_per_day': _intParam(params, 'meals_per_day', 3),
      'excluded': params['excluded_ingredients'] ?? params['excluded'] ?? const [],
      'preferred':
          params['preferred_ingredients'] ?? params['preferred'] ?? const [],
      'disliked': params['disliked_ingredients'] ?? params['disliked'] ?? const [],
      'allergies': params['allergies'] ?? params['allergens'] ?? const [],
    };
  }

  UserSettings _settingsWithOverrides(
    UserSettings settings,
    MealPlannerIntentResult intent,
  ) {
    final params = intent.extractedParameters;
    var nextDietType = settings.dietType;
    if (params['goal'] == 'weight_loss') nextDietType = DietType.cut;
    if (params['goal'] == 'muscle_gain') nextDietType = DietType.bulk;
    if (params['goal'] == 'balanced') nextDietType = DietType.normal;

    return settings.copyWith(
      dailyCalories:
          _intParam(params, 'target_calories', settings.dailyCalories),
      dietType: nextDietType,
      mealsPerDay: _intParam(params, 'meals_per_day', settings.mealsPerDay),
    );
  }

  int _intParam(Map<String, dynamic> params, String key, int fallback) {
    final value = params[key];
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '') ?? fallback;
  }

  MealPlan _withLocalProgress(
    MealPlan plan,
    String mealId,
    MealProgress mealProgress,
  ) {
    final updatedDays = plan.days.map((day) {
      final meals = day.meals.map((meal) {
        return meal.mealId == mealId
            ? meal.copyWithProgress(mealProgress)
            : meal;
      }).toList();
      return day.copyWithMeals(meals);
    }).toList();
    final draft = MealPlan(
      planId: plan.planId,
      days: updatedDays,
      summary: plan.summary,
      progress: plan.progress,
      warnings: plan.warnings,
    );
    return MealPlan(
      planId: draft.planId,
      days: draft.days,
      summary: draft.summary,
      progress: _localProgress(draft),
      warnings: draft.warnings,
    );
  }

  PlanProgress _localProgress(MealPlan plan) {
    final meals = [for (final day in plan.days) ...day.meals];
    final completed = meals.where(
      (meal) =>
          meal.progress.checked ||
          meal.progress.status == 'eaten' ||
          meal.progress.status == 'skipped',
    );
    var completedDays = 0;
    for (final day in plan.days) {
      if (day.meals.isNotEmpty &&
          day.meals.every(
            (meal) =>
                meal.progress.checked ||
                meal.progress.status == 'eaten' ||
                meal.progress.status == 'skipped',
          )) {
        completedDays += 1;
      }
    }
    final completedCount = completed.length;
    final total = meals.length;
    return PlanProgress(
      planId: plan.planId,
      daysTotal: plan.days.length,
      daysCompleted: completedDays,
      mealsTotal: total,
      mealsCompleted: completedCount,
      completionPercent: total == 0 ? 0 : completedCount / total * 100,
      currentDay: plan.days.isEmpty
          ? 1
          : (completedDays + 1 > plan.days.length
              ? plan.days.length
              : completedDays + 1),
    );
  }

  String _planReadyMessage(MealPlan plan, bool savedToProfile) {
    final summary = plan.summary;
    final saveText = savedToProfile ? ' Параметры сохранены в профиль.' : '';
    final warnings = plan.warnings.isEmpty
        ? ''
        : '\n\nПредупреждения: ${plan.warnings.join('; ')}';
    return 'Рацион готов: ${summary.generatedMeals} блюд, '
        '${summary.normal} обычных, ${summary.relaxed} мягких, '
        'пустых слотов: ${summary.emptySlots}, аварийных: ${summary.emergency}.$saveText'
        '\nОткрываю экран рациона.$warnings';
  }

  String _suggestionMessage(List<MealPlanMeal> suggestions) {
    if (suggestions.isEmpty) {
      return 'Не нашёл безопасных вариантов для этого запроса.';
    }
    final lines = suggestions.take(3).map((meal) {
      final kcal = meal.nutritionForUser.calories.toStringAsFixed(0);
      final protein = meal.nutritionForUser.protein.toStringAsFixed(0);
      return '• ${meal.name}: $kcal ккал, белок $protein г, оценка ${meal.score.toStringAsFixed(2)}';
    }).join('\n');
    return 'Вот что можно приготовить:\n$lines';
  }
}

final mealPlannerProvider =
    StateNotifierProvider<MealPlannerNotifier, MealPlannerState>(
  (ref) => MealPlannerNotifier(),
);
