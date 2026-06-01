import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/core/providers/chat_provider.dart';

class HistoryScreen extends ConsumerStatefulWidget {
  const HistoryScreen({super.key});

  @override
  ConsumerState<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends ConsumerState<HistoryScreen> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(chatProvider.notifier).loadHistory());
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(chatProvider);
    final notifier = ref.read(chatProvider.notifier);
    final history = notifier.history;

    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      body: SafeArea(
        child: Stack(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Top bar
                  Padding(
                    padding: const EdgeInsets.only(top: 16, bottom: 24),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        GestureDetector(
                          onTap: () => context.go('/chat'),
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
                  ),

                  // Недавнее
                  const Text(
                    'Недавнее',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: Color(0xFFFFFFFF),
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Список чатов
                  Expanded(
                    child: history.isEmpty
                        ? const Center(
                            child: Text(
                              'Нет истории чатов',
                              style: TextStyle(
                                fontFamily: 'Idiqlat',
                                fontSize: 16,
                                color: Color(0xFFB4B4B4),
                              ),
                            ),
                          )
                        : ListView.builder(
                            itemCount: history.length,
                            itemBuilder: (context, index) {
                              final chat = history[index];
                              return GestureDetector(
                                onTap: () {
                                  ref
                                      .read(chatProvider.notifier)
                                      .openChat(chat.id);
                                  context.go('/chat?id=${chat.id}');
                                },
                                child: Padding(
                                  padding: const EdgeInsets.only(bottom: 20),
                                  child: Text(
                                    chat.title,
                                    style: const TextStyle(
                                      fontFamily: 'Idiqlat',
                                      fontSize: 18,
                                      color: Color(0xFFFFFFFF),
                                    ),
                                  ),
                                ),
                              );
                            },
                          ),
                  ),
                ],
              ),
            ),

            // Кнопка новый Чат
            Positioned(
              bottom: 32,
              right: 24,
              child: GestureDetector(
                onTap: () {
                  ref.read(chatProvider.notifier).newChat();
                  context.go('/chat');
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 28,
                    vertical: 14,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFD9D9D9),
                    borderRadius: BorderRadius.circular(67),
                  ),
                  child: const Text(
                    'Чат',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 20,
                      fontWeight: FontWeight.w900,
                      color: Color(0xFF000000),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
