import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/features/meal_planner/models/meal_plan_models.dart';
import 'package:ai_food/features/meal_planner/providers/meal_planner_provider.dart';

class RecipeDetailScreen extends ConsumerWidget {
  final String mealId;
  final MealPlanMeal? initialMeal;

  const RecipeDetailScreen({
    super.key,
    required this.mealId,
    this.initialMeal,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mealPlannerProvider);
    final planMeal = state.currentPlan?.findMeal(mealId);
    final meal = planMeal ?? initialMeal;
    final isStandaloneRecipe = planMeal == null && initialMeal != null;
    final isBusy = state.status == MealPlannerStatus.generatingPlan;

    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      body: SafeArea(
        child: meal == null
            ? _MissingMeal(onBack: () => context.pop())
            : ListView(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
                children: [
                  Row(
                    children: [
                      IconButton(
                        onPressed: () => context.pop(),
                        icon: const Icon(Icons.arrow_back, color: Colors.white),
                      ),
                      const Expanded(
                        child: Text(
                          'Рецепт',
                          style: TextStyle(
                            fontFamily: 'Idiqlat',
                            color: Colors.white,
                            fontSize: 22,
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (_hasImage(meal)) ...[
                    const SizedBox(height: 8),
                    _RecipeImage(url: meal.recipe.imageUrl!),
                    const SizedBox(height: 18),
                  ] else
                    const SizedBox(height: 8),
                  Text(meal.name, style: _headlineStyle),
                  const SizedBox(height: 8),
                  Text(
                    '${_mealTypeLabel(meal.mealType)} • ${_tierLabel(meal.tier)} • оценка ${meal.score.toStringAsFixed(2)}',
                    style: _mutedStyle,
                  ),
                  const SizedBox(height: 16),
                  _NutritionPanel(
                    title: 'Ваша порция',
                    nutrition: meal.nutritionForUser,
                  ),
                  if (meal.servingsTotal > 1) ...[
                    const SizedBox(height: 10),
                    _NutritionPanel(
                      title: 'Всего приготовлено',
                      nutrition: meal.nutritionTotal,
                    ),
                    const SizedBox(height: 10),
                    _NutritionPanel(
                      title: 'На 1 порцию',
                      nutrition: meal.nutritionPerServing,
                    ),
                  ],
                  const SizedBox(height: 16),
                  _Section(
                    title: meal.servingsTotal > 1
                        ? 'Ингредиенты на ${meal.servingsTotal} порций'
                        : 'Ингредиенты',
                    children:
                        _ingredientLines(meal).map(_BulletLine.new).toList(),
                  ),
                  if (meal.recipe.instructions.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    _Section(
                      title: 'Инструкция',
                      children: [
                        for (int i = 0;
                            i < meal.recipe.instructions.length;
                            i++)
                          _NumberedLine(
                            number: i + 1,
                            text: meal.recipe.instructions[i],
                          ),
                      ],
                    ),
                  ],
                  if (!isStandaloneRecipe) ...[
                    const SizedBox(height: 18),
                    Row(
                      children: [
                        Expanded(
                          child: ElevatedButton.icon(
                            onPressed: () => ref
                                .read(mealPlannerProvider.notifier)
                                .updateMealProgress(
                                  meal,
                                  status: 'cooked',
                                  checked: meal.progress.checked,
                                ),
                            icon: const Icon(Icons.soup_kitchen),
                            label: const Text('Приготовлено'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: ElevatedButton.icon(
                            onPressed: () => ref
                                .read(mealPlannerProvider.notifier)
                                .updateMealProgress(
                                  meal,
                                  status: 'eaten',
                                  checked: true,
                                ),
                            icon: const Icon(Icons.check_circle),
                            label: const Text('Съедено'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: isBusy
                                ? null
                                : () => _replaceMeal(context, ref, meal),
                            icon: const Icon(Icons.swap_horiz),
                            label: const Text('Заменить'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: isBusy
                                ? null
                                : () => _regenerateMeal(context, ref, meal),
                            icon: const Icon(Icons.refresh),
                            label: const Text('Пересобрать'),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
      ),
    );
  }

  Future<void> _replaceMeal(
    BuildContext context,
    WidgetRef ref,
    MealPlanMeal meal,
  ) async {
    await ref.read(mealPlannerProvider.notifier).replaceMeal(meal);
    if (!context.mounted) return;
    final error = ref.read(mealPlannerProvider).error;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(error ?? 'Блюдо заменено')),
    );
  }

  Future<void> _regenerateMeal(
    BuildContext context,
    WidgetRef ref,
    MealPlanMeal meal,
  ) async {
    await ref.read(mealPlannerProvider.notifier).regenerateMeal(meal);
    if (!context.mounted) return;
    final error = ref.read(mealPlannerProvider).error;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(error ?? 'Блюдо пересобрано')),
    );
  }
}

bool _hasImage(MealPlanMeal meal) {
  final url = meal.recipe.imageUrl?.trim();
  return url != null && url.isNotEmpty;
}

class _RecipeImage extends StatefulWidget {
  final String url;

  const _RecipeImage({required this.url});

  @override
  State<_RecipeImage> createState() => _RecipeImageState();
}

class _RecipeImageState extends State<_RecipeImage> {
  bool _hidden = false;

  @override
  Widget build(BuildContext context) {
    if (_hidden) return const SizedBox.shrink();

    final url = widget.url;
    final image = url.startsWith('http://') || url.startsWith('https://')
        ? Image.network(
            url,
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (mounted) setState(() => _hidden = true);
              });
              return const SizedBox.shrink();
            },
          )
        : Image.asset(
            url,
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (mounted) setState(() => _hidden = true);
              });
              return const SizedBox.shrink();
            },
          );

    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        height: 180,
        width: double.infinity,
        child: image,
      ),
    );
  }
}

class _NutritionPanel extends StatelessWidget {
  final String title;
  final MealNutrition nutrition;

  const _NutritionPanel({
    required this.title,
    required this.nutrition,
  });

  @override
  Widget build(BuildContext context) {
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: _titleStyle),
          const SizedBox(height: 8),
          Row(
            children: [
              _MacroPill(label: 'ккал', value: nutrition.calories),
              _MacroPill(label: 'Б', value: nutrition.protein),
              _MacroPill(label: 'Ж', value: nutrition.fat),
              _MacroPill(label: 'У', value: nutrition.carbs),
            ],
          ),
        ],
      ),
    );
  }
}

class _MacroPill extends StatelessWidget {
  final String label;
  final double value;

  const _MacroPill({
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        margin: const EdgeInsets.only(right: 6),
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          color: const Color(0xFF2C2C2C),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Column(
          children: [
            Text(value.toStringAsFixed(0), style: _titleStyle),
            const SizedBox(height: 3),
            Text(label, style: _tinyStyle),
          ],
        ),
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final List<Widget> children;

  const _Section({
    required this.title,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: _titleStyle),
          const SizedBox(height: 10),
          ...children,
        ],
      ),
    );
  }
}

class _BulletLine extends StatelessWidget {
  final String text;

  const _BulletLine(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('• ', style: _mutedStyle),
          Expanded(child: Text(text, style: _mutedStyle)),
        ],
      ),
    );
  }
}

class _NumberedLine extends StatelessWidget {
  final int number;
  final String text;

  const _NumberedLine({
    required this.number,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 24,
            child: Text('$number.', style: _mutedStyle),
          ),
          Expanded(child: Text(text, style: _mutedStyle)),
        ],
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

class _MissingMeal extends StatelessWidget {
  final VoidCallback onBack;

  const _MissingMeal({required this.onBack});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Блюдо не найдено',
              style: _headlineStyle,
            ),
            const SizedBox(height: 12),
            const Text(
              'Откройте экран рациона и выберите блюдо еще раз.',
              style: _mutedStyle,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 18),
            ElevatedButton(
              onPressed: onBack,
              child: const Text('Назад'),
            ),
          ],
        ),
      ),
    );
  }
}

List<String> _ingredientLines(MealPlanMeal meal) {
  final source = meal.recipe.ingredientsDetail.isNotEmpty
      ? meal.recipe.ingredientsDetail
      : meal.recipe.ingredients;
  if (source.isEmpty) return const ['Ингредиенты недоступны.'];
  return source.map(_ingredientText).toList();
}

String _ingredientText(dynamic item) {
  if (item is Map) {
    final name = item['name'] ?? item['ingredient'] ?? item['food'] ?? 'Ингредиент';
    final amount = item['grams'] ?? item['amount'] ?? item['quantity'];
    final unit = item['unit'] ?? (item['grams'] != null ? 'г' : '');
    if (amount != null) return '$name - $amount $unit'.trim();
    return name.toString();
  }
  return item.toString();
}

String _mealTypeLabel(String value) {
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

String _tierLabel(String value) {
  switch (value) {
    case 'normal':
      return 'норма';
    case 'relaxed':
      return 'мягкий режим';
    case 'emergency':
      return 'аварийный режим';
    default:
      return value;
  }
}

const _headlineStyle = TextStyle(
  fontFamily: 'Idiqlat',
  color: Color(0xFFEDEDED),
  fontSize: 26,
);

const _titleStyle = TextStyle(
  fontFamily: 'Idiqlat',
  color: Color(0xFFEDEDED),
  fontSize: 17,
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
