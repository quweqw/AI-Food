import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/core/providers/settings_provider.dart';
import 'package:ai_food/features/meal_planner/models/meal_plan_models.dart';
import 'package:ai_food/features/meal_planner/providers/meal_planner_provider.dart';

class MealPlannerScreen extends ConsumerStatefulWidget {
  const MealPlannerScreen({super.key});

  @override
  ConsumerState<MealPlannerScreen> createState() => _MealPlannerScreenState();
}

class _MealPlannerScreenState extends ConsumerState<MealPlannerScreen> {
  @override
  void initState() {
    super.initState();
    Future.microtask(
      () => ref.read(mealPlannerProvider.notifier).loadLatestPlan(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final planner = ref.watch(mealPlannerProvider);
    final settings = ref.watch(settingsProvider);
    final plan = planner.currentPlan;
    final isLoading = planner.status == MealPlannerStatus.generatingPlan ||
        planner.status == MealPlannerStatus.parsingIntent;

    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 10),
              child: Row(
                children: [
                  IconButton(
                    onPressed: () => context.pop(),
                    icon: const Icon(Icons.arrow_back, color: Colors.white),
                  ),
                  const Expanded(
                    child: Text(
                      'Рацион',
                      style: TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 24,
                        color: Color(0xFFEDEDED),
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Составить рацион',
                    onPressed: isLoading
                        ? null
                        : () => ref
                            .read(mealPlannerProvider.notifier)
                            .generateDefaultPlan(settings),
                    icon: const Icon(Icons.refresh, color: Colors.white),
                  ),
                ],
              ),
            ),
            if (isLoading) const LinearProgressIndicator(minHeight: 2),
            Expanded(
              child: plan == null
                  ? _EmptyPlanState(
                      error: planner.error,
                      onGenerate: () => ref
                          .read(mealPlannerProvider.notifier)
                          .generateDefaultPlan(settings),
                    )
                  : _PlanBoard(plan: plan, selectedDay: planner.selectedDay),
            ),
          ],
        ),
      ),
    );
  }
}

class _PlanBoard extends ConsumerWidget {
  final MealPlan plan;
  final int selectedDay;

  const _PlanBoard({
    required this.plan,
    required this.selectedDay,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final day = plan.days.firstWhere(
      (item) => item.day == selectedDay,
      orElse: () =>
          plan.days.isNotEmpty ? plan.days.first : const MealPlanDay(day: 1),
    );

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        _SummaryCard(plan: plan, day: day),
        const SizedBox(height: 12),
        _ProgressCard(plan: plan),
        if (plan.warnings.isNotEmpty) ...[
          const SizedBox(height: 12),
          _WarningsCard(warnings: plan.warnings),
        ],
        const SizedBox(height: 16),
        SizedBox(
          height: 44,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: plan.days.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, index) {
              final item = plan.days[index];
              final selected = item.day == day.day;
              return ChoiceChip(
                label: Text('День ${item.day}'),
                selected: selected,
                onSelected: (_) =>
                    ref.read(mealPlannerProvider.notifier).selectDay(item.day),
                selectedColor: const Color(0xFFEDEDED),
                backgroundColor: const Color(0xFF242424),
                labelStyle: TextStyle(
                  color: selected ? const Color(0xFF151515) : Colors.white,
                  fontFamily: 'Idiqlat',
                ),
              );
            },
          ),
        ),
        const SizedBox(height: 16),
        ...day.meals.map((meal) => _MealCard(meal: meal)),
      ],
    );
  }
}

class _SummaryCard extends StatelessWidget {
  final MealPlan plan;
  final MealPlanDay day;

  const _SummaryCard({
    required this.plan,
    required this.day,
  });

  @override
  Widget build(BuildContext context) {
    final macros = day.macroSummary;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'День ${day.day}',
                  style: _titleStyle,
                ),
              ),
              Text(
                'оценка ${day.score.toStringAsFixed(2)}',
                style: _mutedStyle,
              ),
            ],
          ),
          const SizedBox(height: 12),
          _MacroRow(
            label: 'Калории',
            value: macros.calories,
            target: day.targetCalories,
            unit: 'ккал',
          ),
          _MacroRow(label: 'Белки', value: macros.protein, unit: 'г'),
          _MacroRow(label: 'Жиры', value: macros.fat, unit: 'г'),
          _MacroRow(label: 'Углеводы', value: macros.carbs, unit: 'г'),
          const Divider(color: Color(0xFF3A3A3A)),
          Text(
            'Качество: ${plan.summary.normal} нормальных, ${plan.summary.relaxed} мягких, ${plan.summary.emergency} аварийных',
            style: _mutedStyle,
          ),
        ],
      ),
    );
  }
}

class _ProgressCard extends StatelessWidget {
  final MealPlan plan;

  const _ProgressCard({required this.plan});

  @override
  Widget build(BuildContext context) {
    final progress = plan.progress;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(child: Text('Прогресс', style: _titleStyle)),
              Text(
                '${progress.completionPercent.toStringAsFixed(1)}%',
                style: _titleStyle,
              ),
            ],
          ),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              minHeight: 8,
              value: progress.mealsTotal == 0
                  ? 0
                  : progress.mealsCompleted / progress.mealsTotal,
              backgroundColor: const Color(0xFF333333),
              valueColor: const AlwaysStoppedAnimation(Color(0xFFEDEDED)),
            ),
          ),
          const SizedBox(height: 10),
          Text(
            '${progress.mealsCompleted}/${progress.mealsTotal} блюд отмечено • день ${progress.currentDay}/${progress.daysTotal}',
            style: _mutedStyle,
          ),
        ],
      ),
    );
  }
}

class _WarningsCard extends StatelessWidget {
  final List<String> warnings;

  const _WarningsCard({required this.warnings});

  @override
  Widget build(BuildContext context) {
    return _Panel(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, color: Color(0xFFE9C46A), size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              warnings.join('\n'),
              style: _mutedStyle,
            ),
          ),
        ],
      ),
    );
  }
}

class _MealCard extends ConsumerWidget {
  final MealPlanMeal meal;

  const _MealCard({required this.meal});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final checked = meal.progress.checked || meal.progress.status == 'eaten';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => context.push('/meal-planner/recipe/${meal.mealId}'),
        child: _Panel(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Checkbox(
                value: checked,
                activeColor: const Color(0xFFEDEDED),
                checkColor: const Color(0xFF151515),
                onChanged: (value) {
                  ref.read(mealPlannerProvider.notifier).updateMealProgress(
                        meal,
                        status: value == true ? 'eaten' : 'planned',
                        checked: value == true,
                      );
                },
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            meal.name,
                            style: _titleStyle,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        _TierBadge(tier: meal.tier),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '${_mealType(meal.mealType)} • ${meal.nutritionForUser.calories.toStringAsFixed(0)} ккал • Б ${meal.nutritionForUser.protein.toStringAsFixed(0)} / Ж ${meal.nutritionForUser.fat.toStringAsFixed(0)} / У ${meal.nutritionForUser.carbs.toStringAsFixed(0)}',
                      style: _mutedStyle,
                    ),
                    if (meal.mainCarb != null || meal.mainProteins.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(
                          [
                            if (meal.mainCarb != null) 'углевод: ${meal.mainCarb}',
                            if (meal.mainProteins.isNotEmpty)
                              'белок: ${meal.mainProteins.join(', ')}',
                          ].join(' • '),
                          style: _tinyStyle,
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyPlanState extends StatelessWidget {
  final String? error;
  final VoidCallback onGenerate;

  const _EmptyPlanState({
    required this.error,
    required this.onGenerate,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.restaurant_menu, color: Colors.white70, size: 46),
            const SizedBox(height: 16),
            const Text(
              'Рацион пока не создан',
              style: TextStyle(
                fontFamily: 'Idiqlat',
                color: Colors.white,
                fontSize: 24,
              ),
            ),
            if (error != null) ...[
              const SizedBox(height: 10),
              Text(error!, style: _mutedStyle, textAlign: TextAlign.center),
            ],
            const SizedBox(height: 18),
            ElevatedButton.icon(
              onPressed: onGenerate,
              icon: const Icon(Icons.auto_awesome),
              label: const Text('Составить рацион на 7 дней'),
            ),
          ],
        ),
      ),
    );
  }
}

class _MacroRow extends StatelessWidget {
  final String label;
  final double value;
  final double? target;
  final String unit;

  const _MacroRow({
    required this.label,
    required this.value,
    this.target,
    required this.unit,
  });

  @override
  Widget build(BuildContext context) {
    final targetText =
        target == null || target == 0 ? '' : ' / ${target!.toStringAsFixed(0)}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(child: Text(label, style: _mutedStyle)),
          Text(
            '${value.toStringAsFixed(0)}$targetText $unit',
            style: _valueStyle,
          ),
        ],
      ),
    );
  }
}

class _TierBadge extends StatelessWidget {
  final String tier;

  const _TierBadge({required this.tier});

  @override
  Widget build(BuildContext context) {
    final label = {
          'normal': 'норма',
          'relaxed': 'мягкий',
          'emergency': 'аварийный',
        }[tier] ??
        tier;
    final color = tier == 'normal'
        ? const Color(0xFF79D28B)
        : tier == 'relaxed'
            ? const Color(0xFFE9C46A)
            : const Color(0xFFE76F51);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        color: color.withValues(alpha: 0.16),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontFamily: 'Idiqlat',
          color: color,
          fontSize: 12,
        ),
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  final Widget child;

  const _Panel({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF202020),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF303030)),
      ),
      child: child,
    );
  }
}

String _mealType(String value) {
  switch (value) {
    case 'breakfast':
      return 'Завтрак';
    case 'lunch':
      return 'Обед';
    case 'dinner':
      return 'Ужин';
    case 'snack':
      return 'Перекус';
    case 'завтрак':
    case 'обед':
    case 'ужин':
    case 'перекус':
      return value;
    default:
      return value;
  }
}

const _titleStyle = TextStyle(
  fontFamily: 'Idiqlat',
  color: Color(0xFFEDEDED),
  fontSize: 18,
);

const _valueStyle = TextStyle(
  fontFamily: 'Idiqlat',
  color: Color(0xFFEDEDED),
  fontSize: 15,
);

const _mutedStyle = TextStyle(
  fontFamily: 'Idiqlat',
  color: Color(0xFFB4B4B4),
  fontSize: 14,
);

const _tinyStyle = TextStyle(
  fontFamily: 'Idiqlat',
  color: Color(0xFF8E8E8E),
  fontSize: 12,
);
