import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:ai_food/core/providers/chat_provider.dart';
import 'package:ai_food/core/providers/settings_provider.dart';
import 'package:ai_food/core/services/api_service.dart';
import 'package:ai_food/features/meal_planner/models/meal_plan_models.dart';
import 'package:ai_food/features/meal_planner/providers/meal_planner_provider.dart';

class ChatScreen extends ConsumerStatefulWidget {
  final String? chatId;
  const ChatScreen({super.key, this.chatId});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _messageController = TextEditingController();
  final _scrollController = ScrollController();
  final _picker = ImagePicker();
  bool _showPhotoPanel = false;

  final List<String> _quickSuggestions = [
    'Составь план питания на неделю',
    'Предложи рецепт с курицей на ужин',
  ];

  @override
  void initState() {
    super.initState();
    _messageController.addListener(() => setState(() {}));
    Future.microtask(() async {
      await ref.read(chatProvider.notifier).loadHistory();
      _openRequestedChat();
      await _loadProfile();
    });
  }

  @override
  void didUpdateWidget(covariant ChatScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.chatId != oldWidget.chatId) {
      Future.microtask(_openRequestedChat);
    }
  }

  void _openRequestedChat() {
    final chatId = widget.chatId;
    if (chatId != null && chatId.isNotEmpty) {
      ref.read(chatProvider.notifier).openChat(chatId);
    }
  }

  Future<void> _loadProfile() async {
    try {
      final settingsData = await apiService.getSettings();
      await ref.read(settingsProvider.notifier).loadFromBackend(settingsData);
    } catch (_) {
      // The next authenticated request will surface token/profile errors.
    }
  }

  @override
  void dispose() {
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _sendMessage(String text) async {
    if (text.trim().isEmpty) return;

    final notifier = ref.read(chatProvider.notifier);
    final settings = ref.read(settingsProvider);
    final historyForApi = _chatHistoryForApi(
      notifier.currentChat?.messages ?? const [],
    );

    notifier.addMessage(ChatMessage(text: text.trim(), isUser: true));
    _messageController.clear();
    _scrollToBottom();

    final mealPlannerResult = await ref
        .read(mealPlannerProvider.notifier)
        .tryHandleChatMessage(text.trim(), settings);
    if (mealPlannerResult.handled) {
      notifier.addMessage(
        ChatMessage(text: mealPlannerResult.message, isUser: false),
      );
      _scrollToBottom();
      if (mealPlannerResult.openPlan && mounted) {
        context.push('/meal-planner');
      }
      return;
    }

    notifier.addMessage(ChatMessage(text: '', isUser: false));

    String aiResponse = '';

    try {
      final stream = apiService.chatStream(
        message: text.trim(),
        history: historyForApi,
        allergens: settings.allergens,
        favoriteProducts: settings.favoriteProducts,
        dislikedProducts: settings.dislikedProducts,
        excludedProducts: settings.excludedProducts,
        dailyCalories: settings.dailyCalories,
        dietType: settings.dietType.name,
        age: settings.age,
        gender: settings.gender == Gender.male ? 'male' : 'female',
        height: settings.height,
        weight: settings.weight,
      );

      await for (final chunk in stream) {
        aiResponse += chunk;
        notifier.updateLastMessage(aiResponse);
        _scrollToBottom();
      }
    } catch (e) {
      notifier.updateLastMessage('Ошибка соединения с сервером');
    }
  }

  List<Map<String, String>> _chatHistoryForApi(List<ChatMessage> messages) {
    final history = <Map<String, String>>[];
    for (final message in messages.reversed) {
      if (message.isLoading || message.kind != 'text') continue;
      final content = message.text.trim();
      if (content.isEmpty) continue;
      history.add({
        'role': message.isUser ? 'user' : 'assistant',
        'content': content,
      });
      if (history.length >= 12) break;
    }
    return history.reversed.toList();
  }

  Future<void> _confirmMealPlanner(String action) async {
    final notifier = ref.read(chatProvider.notifier);
    final settings = ref.read(settingsProvider);

    final result = await ref
        .read(mealPlannerProvider.notifier)
        .confirmPending(action, settings);

    notifier.addMessage(ChatMessage(text: result.message, isUser: false));
    _scrollToBottom();

    if (action == 'save_to_profile') {
      try {
        final settingsData = await apiService.getSettings();
        await ref.read(settingsProvider.notifier).loadFromBackend(settingsData);
      } catch (_) {}
    }

    if (result.openPlan && mounted) {
      context.push('/meal-planner');
    }
  }

  Future<void> _pickImage(ImageSource source) async {
    setState(() => _showPhotoPanel = false);

    final notifier = ref.read(chatProvider.notifier);
    final settings = ref.read(settingsProvider);

    try {
      final file = await _picker.pickImage(
        source: source,
        maxWidth: 1280,
        imageQuality: 85,
      );
      if (file == null) return;

      final bytes = await file.readAsBytes();

      notifier.addMessage(
        ChatMessage(
          text: 'Фото',
          isUser: true,
          kind: 'image',
          imageBytes: Uint8List.fromList(bytes),
        ),
      );
      notifier.addMessage(
        ChatMessage(
          text: 'Анализирую фото',
          isUser: false,
          isLoading: true,
        ),
      );
      _scrollToBottom();

      final result = await apiService.recognizeImage(
        imageBytes: bytes,
        filename: file.name,
        settings: settings,
      );

      final suggestions = await _loadSimilarRecipes(result, settings);
      notifier.replaceLastMessage(
        ChatMessage(
          text: 'Распознавание готово',
          isUser: false,
          kind: 'recognition',
          metadata: _recognitionMetadata(result, suggestions),
        ),
      );
      _scrollToBottom();
      if (mounted) setState(() {});
    } catch (e) {
      notifier.updateLastMessage('Ошибка при распознавании: $e');
    }
  }

  Future<List<MealPlanMeal>> _loadSimilarRecipes(
    Map<String, dynamic> recognition,
    UserSettings settings,
  ) async {
    final ingredients = (recognition['ingredients'] as List? ?? const [])
        .map((item) => item.toString())
        .where((item) => item.trim().isNotEmpty)
        .toList();
    if (ingredients.isEmpty) return const [];

    try {
      return await apiService.suggestDinner({
        'meal_type': 'dinner',
        'target_calories': (settings.dailyCalories / settings.mealsPerDay)
            .round()
            .clamp(250, 1200),
        'servings': 1,
        'people_count': 1,
        'ingredients_available': ingredients,
        'temporary_overrides': {
          'target_calories': settings.dailyCalories,
          'goal': goalForSettings(settings),
          'meals_per_day': settings.mealsPerDay,
          'allergies': settings.allergens,
          'excluded': settings.excludedProducts,
          'preferred': settings.favoriteProducts,
          'disliked': settings.dislikedProducts,
        },
      });
    } catch (_) {
      return const [];
    }
  }

  Map<String, dynamic> _recognitionMetadata(
    Map<String, dynamic> result,
    List<MealPlanMeal> suggestions,
  ) {
    final meal = result['meal']?.toString().trim().isNotEmpty == true
        ? result['meal'].toString()
        : 'Блюдо';
    final nutrition =
        Map<String, dynamic>.from(result['nutrition'] as Map? ?? const {});
    final ingredients = (result['ingredients'] as List? ?? const [])
        .map((item) => item.toString())
        .where((item) => item.trim().isNotEmpty)
        .toList();
    final score = _asNum(result['score']);
    final recipe = Map<String, dynamic>.from(result['recipe'] as Map? ?? const {});
    final steps = _recipeSteps(recipe, ingredients);
    final tips = recipe['tips']?.toString().trim() ?? '';

    return {
      'meal': meal,
      'confidence': score == null ? null : score.clamp(0, 1).toDouble(),
      'ingredients': ingredients,
      'nutrition': {
        'calories': _asNum(nutrition['calories'])?.toDouble(),
        'protein': _asNum(nutrition['protein'])?.toDouble(),
        'fat': _asNum(nutrition['fat'])?.toDouble(),
        'carbs': _asNum(nutrition['carbs'])?.toDouble(),
      },
      'recipe_steps': steps,
      'tips': tips,
      'suggestions': suggestions.take(3).map((meal) => meal.toJson()).toList(),
    };
  }

  List<String> _recipeSteps(
    Map<String, dynamic> recipe,
    List<String> ingredients,
  ) {
    final rawSteps = recipe['instructions'] ?? recipe['steps'];
    final steps = (rawSteps as List? ?? const [])
        .map((item) => item.toString().trim())
        .where((item) => item.isNotEmpty)
        .toList();
    if (steps.isNotEmpty) return steps;

    final ingredientText = ingredients.isEmpty
        ? 'ингредиенты'
        : ingredients.take(6).join(', ');
    return [
      'Подготовьте $ingredientText.',
      'Нарежьте продукты удобными кусочками и соедините в миске.',
      'Приправьте по вкусу, аккуратно перемешайте и подавайте свежим.',
    ];
  }

  num? _asNum(dynamic value) {
    if (value is num) return value;
    return num.tryParse(value?.toString() ?? '');
  }

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final notifier = ref.watch(chatProvider.notifier);
    ref.watch(chatProvider);
    final mealPlannerState = ref.watch(mealPlannerProvider);
    final messages = notifier.currentChat?.messages ?? [];

    final bottomInset = MediaQuery.of(context).viewInsets.bottom;
    final isKeyboardVisible = bottomInset > 0;
    final showSuggestions = messages.isEmpty &&
        !isKeyboardVisible &&
        _messageController.text.isEmpty;

    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      resizeToAvoidBottomInset: false,
      body: SafeArea(
        child: Stack(
          children: [
            Column(
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
                      GestureDetector(
                        onTap: () => context.push('/history'),
                        child: const Row(
                          children: [
                            Icon(Icons.circle,
                                size: 12, color: Color(0xFFB4B4B4)),
                            SizedBox(width: 8),
                            Text(
                              'AI Food',
                              style: TextStyle(
                                fontFamily: 'Idiqlat',
                                fontSize: 22,
                                color: Color(0xFFB4B4B4),
                              ),
                            ),
                          ],
                        ),
                      ),
                      Row(
                        children: [
                          IconButton(
                            tooltip: 'Рацион',
                            onPressed: () => context.push('/meal-planner'),
                            icon: const Icon(
                              Icons.calendar_month,
                              color: Color(0xFFB4B4B4),
                            ),
                          ),
                          GestureDetector(
                            onTap: () => context.push('/settings'),
                            child: const Text(
                              'Профиль',
                              style: TextStyle(
                                fontFamily: 'Idiqlat',
                                fontSize: 22,
                                color: Color(0xFFB4B4B4),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),

                // Сообщения
                Expanded(
                  child: messages.isEmpty
                      ? const SizedBox()
                      : ListView.builder(
                          controller: _scrollController,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 8,
                          ),
                          itemCount: messages.length,
                          itemBuilder: (context, index) =>
                              _buildMessage(messages[index]),
                        ),
                ),

                // Quick suggestions
                if (showSuggestions)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                    child: Row(
                      children: _quickSuggestions.map((text) {
                        return Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 6),
                            child: GestureDetector(
                              onTap: () => _sendMessage(text),
                              child: Container(
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: const Color(0xFFD9D9D9)
                                      .withValues(alpha: 0.07),
                                  borderRadius: BorderRadius.circular(20),
                                ),
                                child: Text(
                                  text,
                                  style: const TextStyle(
                                    fontFamily: 'Idiqlat',
                                    fontSize: 14,
                                    color: Color(0xFFFFFFFF),
                                  ),
                                  textAlign: TextAlign.center,
                                ),
                              ),
                            ),
                          ),
                        );
                      }).toList(),
                    ),
                  ),

                // Поле ввода
                if (mealPlannerState.status ==
                    MealPlannerStatus.waitingConfirmation)
                  _buildMealPlannerConfirmation(mealPlannerState),

                AnimatedPadding(
                  duration: const Duration(milliseconds: 200),
                  curve: Curves.easeOut,
                  padding: EdgeInsets.only(bottom: bottomInset),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                    child: Row(
                      children: [
                        GestureDetector(
                          onTap: () => setState(() => _showPhotoPanel = true),
                          child: Container(
                            width: 48,
                            height: 48,
                            decoration: const BoxDecoration(
                              color: Color(0xFF696969),
                              shape: BoxShape.circle,
                            ),
                            child: const Icon(Icons.add,
                                color: Colors.white, size: 24),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Container(
                            height: 48,
                            decoration: BoxDecoration(
                              color: const Color(0xFF696969),
                              borderRadius: BorderRadius.circular(33),
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: TextField(
                                    controller: _messageController,
                                    style: const TextStyle(
                                      fontFamily: 'Idiqlat',
                                      fontSize: 16,
                                      color: Colors.white,
                                    ),
                                    decoration: const InputDecoration(
                                      hintText: 'Спросите AI Food',
                                      hintStyle: TextStyle(
                                        fontFamily: 'Idiqlat',
                                        fontSize: 16,
                                        color: Colors.white,
                                      ),
                                      border: InputBorder.none,
                                      contentPadding: EdgeInsets.symmetric(
                                        horizontal: 16,
                                        vertical: 12,
                                      ),
                                    ),
                                    onSubmitted: _sendMessage,
                                  ),
                                ),
                                Padding(
                                  padding: const EdgeInsets.only(right: 6),
                                  child: GestureDetector(
                                    onTap: () =>
                                        _sendMessage(_messageController.text),
                                    child: Container(
                                      width: 36,
                                      height: 36,
                                      decoration: const BoxDecoration(
                                        color: Color(0xFFAEAEAE),
                                        shape: BoxShape.circle,
                                      ),
                                      child: const Icon(Icons.arrow_upward,
                                          color: Colors.white, size: 18),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
            if (_showPhotoPanel) _buildPhotoPanel(),
          ],
        ),
      ),
    );
  }

  Widget _buildMealPlannerConfirmation(MealPlannerState state) {
    final message = state.pendingIntent?.confirmationMessage ??
        'Как применить параметры рациона?';
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: const Color(0xFF202020),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFF363636)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message,
              style: const TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 15,
                color: Colors.white,
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton(
                  onPressed: () => _confirmMealPlanner('apply_once'),
                  child: const Text('Только для этого плана'),
                ),
                OutlinedButton(
                  onPressed: () => _confirmMealPlanner('save_to_profile'),
                  child: const Text('Сохранить в профиль'),
                ),
                TextButton(
                  onPressed: () => _confirmMealPlanner('reject'),
                  child: const Text('Отклонить'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMessage(ChatMessage message) {
    if (message.isUser) {
      if (message.kind == 'image' && message.imageBytes != null) {
        return Align(
          alignment: Alignment.centerRight,
          child: Container(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.72,
              maxHeight: 260,
            ),
            margin: const EdgeInsets.only(bottom: 12),
            decoration: const BoxDecoration(
              color: Color(0xFF1F1F1F),
              borderRadius: BorderRadius.only(
                topLeft: Radius.circular(22),
                bottomLeft: Radius.circular(22),
                bottomRight: Radius.circular(22),
                topRight: Radius.circular(4),
              ),
            ),
            clipBehavior: Clip.antiAlias,
            child: Image.memory(
              message.imageBytes!,
              width: double.infinity,
              height: 220,
              fit: BoxFit.cover,
            ),
          ),
        );
      }

      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.75,
          ),
          margin: const EdgeInsets.only(bottom: 12),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          decoration: const BoxDecoration(
            color: Color(0xFF1F1F1F),
            borderRadius: BorderRadius.only(
              topLeft: Radius.circular(44),
              bottomLeft: Radius.circular(44),
              bottomRight: Radius.circular(44),
              topRight: Radius.circular(0),
            ),
          ),
          child: Text(
            message.text,
            style: const TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 16,
              color: Colors.white,
            ),
          ),
        ),
      );
    }

    if (message.kind == 'recognition' && message.metadata != null) {
      return Align(
        alignment: Alignment.centerLeft,
        child: Container(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.92,
          ),
          margin: const EdgeInsets.only(bottom: 14),
          child: _RecognitionResultCard(
            data: message.metadata!,
            onOpenMeal: (meal) => context.push(
              '/meal-planner/recipe/${meal.mealId}',
              extra: meal,
            ),
          ),
        ),
      );
    }

    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.9,
        ),
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: message.isLoading
            ? _ShimmerText(message.text)
            : Text(
                message.text,
                style: const TextStyle(
                  fontFamily: 'Idiqlat',
                  fontSize: 16,
                  color: Colors.white,
                ),
              ),
      ),
    );
  }

  Widget _buildPhotoPanel() {
    return Positioned(
      bottom: 0,
      left: 0,
      right: 0,
      child: GestureDetector(
        onVerticalDragEnd: (details) {
          if (details.primaryVelocity! > 200) {
            setState(() => _showPhotoPanel = false);
          }
        },
        child: Container(
          decoration: const BoxDecoration(
            color: Color(0xFF696969),
            borderRadius: BorderRadius.only(
              topLeft: Radius.circular(55),
              topRight: Radius.circular(55),
            ),
          ),
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 48),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 80,
                height: 5,
                margin: const EdgeInsets.only(bottom: 24),
                decoration: BoxDecoration(
                  color: const Color(0xFFD9D9D9),
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              Row(
                children: [
                  Expanded(
                    child: GestureDetector(
                      onTap: () => _pickImage(ImageSource.camera),
                      child: Container(
                        height: 110,
                        decoration: BoxDecoration(
                          color: const Color(0xFF363636),
                          borderRadius: BorderRadius.circular(62),
                        ),
                        child: const Center(
                          child: Text(
                            'Камера',
                            style: TextStyle(
                              fontFamily: 'Idiqlat',
                              fontSize: 20,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: GestureDetector(
                      onTap: () => _pickImage(ImageSource.gallery),
                      child: Container(
                        height: 110,
                        decoration: BoxDecoration(
                          color: const Color(0xFF363636),
                          borderRadius: BorderRadius.circular(62),
                        ),
                        child: const Center(
                          child: Text(
                            'Фото',
                            style: TextStyle(
                              fontFamily: 'Idiqlat',
                              fontSize: 20,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ShimmerText extends StatefulWidget {
  final String text;

  const _ShimmerText(this.text);

  @override
  State<_ShimmerText> createState() => _ShimmerTextState();
}

class _ShimmerTextState extends State<_ShimmerText>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final value = _controller.value;
        return ShaderMask(
          blendMode: BlendMode.srcIn,
          shaderCallback: (bounds) => LinearGradient(
            begin: Alignment(-1.4 + value * 2.8, 0),
            end: Alignment(-0.4 + value * 2.8, 0),
            colors: const [
              Color(0xFF8D8D8D),
              Color(0xFFFFFFFF),
              Color(0xFF8D8D8D),
            ],
          ).createShader(bounds),
          child: child,
        );
      },
      child: Text(
        widget.text,
        style: const TextStyle(
          fontFamily: 'Idiqlat',
          fontSize: 16,
          fontWeight: FontWeight.w900,
          color: Colors.white,
        ),
      ),
    );
  }
}

class _RecognitionResultCard extends StatelessWidget {
  final Map<String, dynamic> data;
  final ValueChanged<MealPlanMeal> onOpenMeal;

  const _RecognitionResultCard({
    required this.data,
    required this.onOpenMeal,
  });

  @override
  Widget build(BuildContext context) {
    final meal = data['meal']?.toString() ?? 'Блюдо';
    final confidence = _recognitionDouble(data['confidence']);
    final nutrition = data['nutrition'] is Map
        ? Map<String, dynamic>.from(data['nutrition'])
        : const <String, dynamic>{};
    final ingredients = _recognitionStringList(data['ingredients']);
    final steps = _recognitionStringList(data['recipe_steps']);
    final tips = data['tips']?.toString().trim() ?? '';
    final suggestions = _recognitionMeals(data['suggestions']);

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF202020),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF333333)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Я распознал блюдо',
                      style: TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 13,
                        color: Colors.white.withValues(alpha: 0.62),
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      meal,
                      style: const TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 20,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
              if (confidence != null)
                _SmallBadge(
                  '${(confidence * 100).round()}%',
                  Icons.auto_awesome,
                ),
            ],
          ),
          const SizedBox(height: 14),
          _SectionTitle('КБЖУ, примерно на 100 г'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _MacroTile('Ккал', _nutritionValue(nutrition, 'calories', 0)),
              _MacroTile('Белки', '${_nutritionValue(nutrition, 'protein', 1)} г'),
              _MacroTile('Жиры', '${_nutritionValue(nutrition, 'fat', 1)} г'),
              _MacroTile('Углеводы', '${_nutritionValue(nutrition, 'carbs', 1)} г'),
            ],
          ),
          const SizedBox(height: 16),
          _SectionTitle('Что видно на фото'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: ingredients.isEmpty
                ? const [_IngredientPill('не удалось определить')]
                : ingredients.map(_IngredientPill.new).toList(),
          ),
          const SizedBox(height: 16),
          _SectionTitle('Быстрый рецепт'),
          const SizedBox(height: 8),
          for (int i = 0; i < steps.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 7),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${i + 1}.',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 14,
                      color: Colors.white.withValues(alpha: 0.64),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      steps[i],
                      style: TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 14,
                        height: 1.3,
                        color: Colors.white.withValues(alpha: 0.86),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          if (tips.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              tips,
              style: TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 13,
                height: 1.35,
                color: Colors.white.withValues(alpha: 0.62),
              ),
            ),
          ],
          if (suggestions.isNotEmpty) ...[
            const SizedBox(height: 16),
            _SectionTitle('Похожие рецепты'),
            const SizedBox(height: 8),
            for (final suggestion in suggestions)
              _SuggestionTile(
                meal: suggestion,
                onTap: () => onOpenMeal(suggestion),
              ),
          ],
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;

  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontFamily: 'Idiqlat',
        fontSize: 15,
        fontWeight: FontWeight.w900,
        color: Colors.white,
      ),
    );
  }
}

class _SmallBadge extends StatelessWidget {
  final String text;
  final IconData icon;

  const _SmallBadge(this.text, this.icon);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFF2B2B2B),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: const Color(0xFFC79BFF)),
          const SizedBox(width: 5),
          Text(
            text,
            style: const TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 13,
              color: Colors.white,
            ),
          ),
        ],
      ),
    );
  }
}

class _MacroTile extends StatelessWidget {
  final String label;
  final String value;

  const _MacroTile(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 108,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF2A2A2A),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            value,
            style: const TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 16,
              fontWeight: FontWeight.w900,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label,
            style: TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 12,
              color: Colors.white.withValues(alpha: 0.56),
            ),
          ),
        ],
      ),
    );
  }
}

class _IngredientPill extends StatelessWidget {
  final String text;

  const _IngredientPill(this.text);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFF292929),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF383838)),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontFamily: 'Idiqlat',
          fontSize: 13,
          color: Colors.white.withValues(alpha: 0.84),
        ),
      ),
    );
  }
}

class _SuggestionTile extends StatelessWidget {
  final MealPlanMeal meal;
  final VoidCallback onTap;

  const _SuggestionTile({
    required this.meal,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: const Color(0xFF292929),
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        meal.name,
                        style: const TextStyle(
                          fontFamily: 'Idiqlat',
                          fontSize: 15,
                          fontWeight: FontWeight.w900,
                          color: Colors.white,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${meal.nutritionForUser.calories.toStringAsFixed(0)} ккал  '
                        'Б ${meal.nutritionForUser.protein.toStringAsFixed(0)} г  '
                        'Ж ${meal.nutritionForUser.fat.toStringAsFixed(0)} г  '
                        'У ${meal.nutritionForUser.carbs.toStringAsFixed(0)} г',
                        style: TextStyle(
                          fontFamily: 'Idiqlat',
                          fontSize: 12,
                          color: Colors.white.withValues(alpha: 0.58),
                        ),
                      ),
                    ],
                  ),
                ),
                Icon(
                  Icons.chevron_right,
                  color: Colors.white.withValues(alpha: 0.55),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

double? _recognitionDouble(dynamic value) {
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '');
}

String _nutritionValue(
  Map<String, dynamic> nutrition,
  String key,
  int fractionDigits,
) {
  final value = _recognitionDouble(nutrition[key]);
  if (value == null) return '-';
  return value.toStringAsFixed(fractionDigits);
}

List<String> _recognitionStringList(dynamic value) {
  if (value is! List) return const [];
  return value
      .map((item) => item.toString().trim())
      .where((item) => item.isNotEmpty)
      .toList();
}

List<MealPlanMeal> _recognitionMeals(dynamic value) {
  if (value is! List) return const [];
  return value
      .whereType<Map>()
      .map((item) => MealPlanMeal.fromJson(Map<String, dynamic>.from(item)))
      .where((meal) => meal.mealId.isNotEmpty)
      .toList();
}
