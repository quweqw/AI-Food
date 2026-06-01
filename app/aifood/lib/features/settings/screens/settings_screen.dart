import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/core/services/api_service.dart';
import 'package:ai_food/core/providers/settings_provider.dart';
import 'package:ai_food/core/data/products_data.dart';
import 'package:ai_food/shared/widgets/product_selector.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  final bool openChatOnSave;

  const SettingsScreen({
    super.key,
    this.openChatOnSave = false,
  });

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  late TextEditingController _ageController;
  late TextEditingController _heightController;
  late TextEditingController _weightController;
  late TextEditingController _caloriesController;

  @override
  void initState() {
    super.initState();
    final s = ref.read(settingsProvider);
    _ageController = TextEditingController(text: s.age.toString());
    _heightController = TextEditingController(text: s.height.toString());
    _weightController = TextEditingController(text: s.weight.toString());
    _caloriesController =
        TextEditingController(text: s.dailyCalories.toString());
  }

  @override
  void dispose() {
    _ageController.dispose();
    _heightController.dispose();
    _weightController.dispose();
    _caloriesController.dispose();
    super.dispose();
  }

  Future<void> _save({bool openChatAfterSave = false}) async {
    final notifier = ref.read(settingsProvider.notifier);
    notifier.updateAge(int.tryParse(_ageController.text) ?? 25);
    notifier.updateHeight(int.tryParse(_heightController.text) ?? 175);
    notifier.updateWeight(double.tryParse(_weightController.text) ?? 70);
    notifier
        .updateDailyCalories(int.tryParse(_caloriesController.text) ?? 2000);

    try {
      await apiService.saveSettings(ref.read(settingsProvider));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Сохранено')),
        );
        if (openChatAfterSave) {
          context.go('/chat');
        }
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось сохранить профиль: $error')),
        );
      }
    }
  }

  Future<void> _calculateCalories() async {
    final notifier = ref.read(settingsProvider.notifier);
    notifier.updateAge(int.tryParse(_ageController.text) ?? 25);
    notifier.updateHeight(int.tryParse(_heightController.text) ?? 175);
    notifier.updateWeight(double.tryParse(_weightController.text) ?? 70);
    late final Map<String, dynamic> result;
    try {
      result = await apiService.calculateCalories(ref.read(settingsProvider));
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось рассчитать калории: $error')),
        );
      }
      return;
    }
    if (!mounted) return;
    final rawTarget = result['target_calories'];
    final target = rawTarget is num ? rawTarget.toInt() : 2000;
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF2A2A2A),
      builder: (_) => Padding(
        padding: const EdgeInsets.fromLTRB(24, 22, 24, 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Рекомендуемая калорийность: $target ккал',
              style: const TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 20,
                color: Colors.white,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              result['explanation']?.toString() ?? '',
              style: TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 14,
                color: Colors.white.withValues(alpha: 0.72),
              ),
            ),
            const SizedBox(height: 18),
            _buildActionButton(
              label: 'Применить к профилю',
              onTap: () async {
                notifier.updateDailyCalories(target);
                _caloriesController.text = target.toString();
                Navigator.pop(context);
                await _save();
              },
              filled: true,
            ),
            const SizedBox(height: 10),
            _buildActionButton(
              label: 'Отмена',
              onTap: () => Navigator.pop(context),
              filled: false,
            ),
          ],
        ),
      ),
    );
  }

  void _openProductSelector({
    required String title,
    required List<String> allProducts,
    required List<String> selected,
    required Function(List<String>) onSave,
  }) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (_) => ProductSelectorSheet(
        title: title,
        allProducts: allProducts,
        selected: selected,
        onSave: onSave,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final settings = ref.watch(settingsProvider);
    final notifier = ref.read(settingsProvider.notifier);

    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      body: SafeArea(
        child: Column(
          children: [
            // Top bar
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: 24,
                vertical: 16,
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    'Профиль',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: Color(0xFFE9E9E9),
                    ),
                  ),
                  GestureDetector(
                    onTap: () => context.go('/chat'),
                    child: const Text(
                      'Чат',
                      style: TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 22,
                        color: Color(0xFFB4B4B4),
                      ),
                    ),
                  ),
                ],
              ),
            ),

            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Email пользователя
                    Center(
                      child: Text(
                        settings.email,
                        style: const TextStyle(
                          fontFamily: 'Idiqlat',
                          fontSize: 22,
                          color: Color(0xFFFFFFFF),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),

                    // Кнопка редактировать профиль
                    Center(
                      child: GestureDetector(
                        onTap: () => context.push('/profile'),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 20,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            border: Border.all(
                              color: const Color(0xFF969696),
                            ),
                            borderRadius: BorderRadius.circular(33),
                          ),
                          child: const Text(
                            'Редактировать профиль',
                            style: TextStyle(
                              fontFamily: 'Idiqlat',
                              fontSize: 14,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),

                    // ПАРАМЕТРЫ
                    _buildSectionLabel('ПАРАМЕТРЫ'),
                    _buildPanel(
                      children: [
                        _buildInputRow(
                          label: 'Возраст',
                          controller: _ageController,
                          keyboardType: TextInputType.number,
                        ),
                        _buildDivider(),
                        _buildGenderRow(settings, notifier),
                        _buildDivider(),
                        _buildActivityRow(settings, notifier),
                        _buildDivider(),
                        _buildInputRow(
                          label: 'Рост',
                          controller: _heightController,
                          keyboardType: TextInputType.number,
                        ),
                        _buildDivider(),
                        _buildInputRow(
                          label: 'Вес',
                          controller: _weightController,
                          keyboardType: const TextInputType.numberWithOptions(
                              decimal: true),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // ПЛАН ПИТАНИЯ
                    _buildSectionLabel('ПЛАН ПИТАНИЯ'),
                    _buildPanel(
                      children: [
                        _buildInputRow(
                          label: 'Калорий в день',
                          controller: _caloriesController,
                          keyboardType: TextInputType.number,
                        ),
                        Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: Align(
                            alignment: Alignment.centerRight,
                            child: GestureDetector(
                              onTap: _calculateCalories,
                              child: const Text(
                                'Рассчитать количество калорий?',
                                style: TextStyle(
                                  fontFamily: 'Idiqlat',
                                  fontSize: 13,
                                  color: Colors.white,
                                  decoration: TextDecoration.underline,
                                  decorationColor: Colors.white,
                                ),
                              ),
                            ),
                          ),
                        ),
                        _buildDivider(),
                        _buildDietRow(settings, notifier),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // ПРОДУКТЫ
                    _buildSectionLabel('ПРОДУКТЫ'),
                    _buildPanel(
                      children: [
                        _buildProductRow(
                          label: 'Аллергены',
                          selected: settings.allergens,
                          onTap: () => _openProductSelector(
                            title: 'Аллергены',
                            allProducts: kAllergens,
                            selected: settings.allergens,
                            onSave: notifier.updateAllergens,
                          ),
                        ),
                        _buildDivider(),
                        _buildProductRow(
                          label: 'Любимые продукты',
                          selected: settings.favoriteProducts,
                          onTap: () => _openProductSelector(
                            title: 'Любимые продукты',
                            allProducts: kProducts,
                            selected: settings.favoriteProducts,
                            onSave: notifier.updateFavoriteProducts,
                          ),
                        ),
                        _buildDivider(),
                        _buildProductRow(
                          label: 'Нелюбимые продукты',
                          selected: settings.dislikedProducts,
                          onTap: () => _openProductSelector(
                            title: 'Нелюбимые продукты',
                            allProducts: kProducts,
                            selected: settings.dislikedProducts,
                            onSave: notifier.updateDislikedProducts,
                          ),
                        ),
                        _buildDivider(),
                        _buildProductRow(
                          label: 'Исключить продукты',
                          selected: settings.excludedProducts,
                          onTap: () => _openProductSelector(
                            title: 'Исключить продукты',
                            allProducts: kProducts,
                            selected: settings.excludedProducts,
                            onSave: notifier.updateExcludedProducts,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 24),

                    // Кнопка Сохранить
                    _buildSaveButton(
                      () => _save(openChatAfterSave: widget.openChatOnSave),
                    ),
                    const SizedBox(height: 32),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ─── Вспомогательные виджеты ───────────────────────────────────────────────

  Widget _buildSectionLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'Idiqlat',
          fontSize: 13,
          color: Colors.white,
          letterSpacing: 1.2,
        ),
      ),
    );
  }

  Widget _buildPanel({required List<Widget> children}) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF222222),
        borderRadius: BorderRadius.circular(28),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(children: children),
    );
  }

  Widget _buildDivider() {
    return Divider(
      color: Colors.white.withValues(alpha: 0.08),
      height: 1,
    );
  }

  Widget _buildInputRow({
    required String label,
    required TextEditingController controller,
    TextInputType keyboardType = TextInputType.text,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 16,
              color: Colors.white,
            ),
          ),
          SizedBox(
            width: 90,
            height: 40,
            child: TextField(
              controller: controller,
              keyboardType: keyboardType,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 16,
                fontWeight: FontWeight.w900,
                color: Colors.white,
              ),
              decoration: BoxDecoration(
                color: const Color(0xFF262626),
                borderRadius: BorderRadius.circular(45),
              ).toInputDecoration(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGenderRow(UserSettings s, SettingsNotifier n) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          const Text(
            'Пол',
            style: TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 16,
              color: Colors.white,
            ),
          ),
          Row(
            children: [
              _buildSelectButton(
                label: 'МУЖ',
                isSelected: s.gender == Gender.male,
                onTap: () => n.updateGender(Gender.male),
              ),
              const SizedBox(width: 8),
              _buildSelectButton(
                label: 'ЖЕН',
                isSelected: s.gender == Gender.female,
                onTap: () => n.updateGender(Gender.female),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildActivityRow(UserSettings s, SettingsNotifier n) {
    final items = const [
      ('sedentary', 'Низкая'),
      ('light', 'Лёгкая'),
      ('moderate', 'Средняя'),
      ('active', 'Высокая'),
    ];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          const Text(
            'Активность',
            style: TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 16,
              color: Colors.white,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Align(
              alignment: Alignment.centerRight,
              child: Wrap(
                alignment: WrapAlignment.end,
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final item in items)
                    _buildSelectButton(
                      label: item.$2,
                      isSelected: s.activityLevel == item.$1,
                      onTap: () => n.updateActivityLevel(item.$1),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildDietRow(UserSettings s, SettingsNotifier n) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _buildSelectButton(
            label: 'МАССОНАБОР',
            isSelected: s.dietType == DietType.bulk,
            onTap: () => n.updateDietType(DietType.bulk),
          ),
          _buildSelectButton(
            label: 'СУШКА',
            isSelected: s.dietType == DietType.cut,
            onTap: () => n.updateDietType(DietType.cut),
          ),
          _buildSelectButton(
            label: 'НОРМА',
            isSelected: s.dietType == DietType.normal,
            onTap: () => n.updateDietType(DietType.normal),
          ),
        ],
      ),
    );
  }

  Widget _buildSelectButton({
    required String label,
    required bool isSelected,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected ? const Color(0xFF404040) : const Color(0xFF262626),
          borderRadius: BorderRadius.circular(45),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontFamily: 'Idiqlat',
            fontSize: 13,
            fontWeight: FontWeight.w900,
            color: isSelected
                ? Colors.white
                : Colors.white.withValues(alpha: 0.19),
          ),
        ),
      ),
    );
  }

  Widget _buildProductRow({
    required String label,
    required List<String> selected,
    required VoidCallback onTap,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: const TextStyle(
                  fontFamily: 'Idiqlat',
                  fontSize: 16,
                  color: Colors.white,
                ),
              ),
              if (selected.isNotEmpty)
                Text(
                  selected.take(3).join(', ') +
                      (selected.length > 3 ? '...' : ''),
                  style: TextStyle(
                    fontFamily: 'Idiqlat',
                    fontSize: 12,
                    color: Colors.white.withValues(alpha: 0.5),
                  ),
                ),
            ],
          ),
          GestureDetector(
            onTap: onTap,
            child: Container(
              width: 40,
              height: 24,
              decoration: BoxDecoration(
                color: const Color(0xFFD9D9D9),
                borderRadius: BorderRadius.circular(45),
              ),
              child: const Icon(
                Icons.add,
                size: 16,
                color: Colors.black,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildActionButton({
    required String label,
    required VoidCallback onTap,
    required bool filled,
  }) {
    return SizedBox(
      width: double.infinity,
      height: 48,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            color: filled ? const Color(0xFF303030) : Colors.transparent,
            borderRadius: BorderRadius.circular(33),
            border: Border.all(color: const Color(0xFF969696)),
          ),
          child: Center(
            child: Text(
              label,
              style: const TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 17,
                color: Colors.white,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSaveButton(VoidCallback onTap) {
    return SizedBox(
      width: double.infinity,
      height: 52,
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            color: const Color(0xFF303030),
            borderRadius: BorderRadius.circular(33),
            border: Border.all(
              color: const Color(0xFF969696),
            ),
          ),
          child: const Center(
            child: Text(
              'Сохранить',
              style: TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 20,
                color: Colors.white,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// Extension для удобства
extension on BoxDecoration {
  InputDecoration toInputDecoration() {
    return InputDecoration(
      filled: true,
      fillColor: color,
      border: OutlineInputBorder(
        borderRadius: borderRadius as BorderRadius,
        borderSide: BorderSide.none,
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 12),
    );
  }
}
