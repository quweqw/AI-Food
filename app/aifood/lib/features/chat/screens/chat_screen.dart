import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/core/providers/chat_provider.dart';

class ChatScreen extends ConsumerStatefulWidget {
  final String? chatId; // если открыт из истории
  const ChatScreen({super.key, this.chatId});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _messageController = TextEditingController();
  final _scrollController = ScrollController();
  bool _showPhotoPanel = false;
  bool _isReadOnly = false; // просмотр из истории

  final List<String> _quickSuggestions = [
    'Составь план питания на неделю',
    'Предложи рецепт с курицей на ужин',
  ];

  @override
  void initState() {
    super.initState();
    _isReadOnly = widget.chatId != null;
    _messageController.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _sendMessage(String text) {
    if (text.trim().isEmpty || _isReadOnly) return;

    final notifier = ref.read(chatProvider.notifier);
    notifier.addMessage(ChatMessage(text: text.trim(), isUser: true));
    _messageController.clear();
    _scrollToBottom();

    // TODO: отправить запрос на backend
    Future.delayed(const Duration(milliseconds: 800), () {
      notifier.addMessage(ChatMessage(
        text: 'Ответ от AI Food на: "${text.trim()}"',
        isUser: false,
      ));
      _scrollToBottom();
    });
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
    final notifier = ref.read(chatProvider.notifier);
    final messages = _isReadOnly
        ? (notifier.getChatById(widget.chatId!)?.messages ?? [])
        : (notifier.currentChat?.messages ?? []);

    final bottomInset = MediaQuery.of(context).viewInsets.bottom;
    final isKeyboardVisible = bottomInset > 0;
    final showSuggestions =
        messages.isEmpty && !isKeyboardVisible && _messageController.text.isEmpty;

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
                        child: Row(
                          children: const [
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
                          'Settings',
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
                                      .withOpacity(0.07),
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

                // Поле ввода — скрыто в режиме просмотра
                if (!_isReadOnly)
                  AnimatedPadding(
                    duration: const Duration(milliseconds: 200),
                    curve: Curves.easeOut,
                    padding: EdgeInsets.only(bottom: bottomInset),
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                      child: Row(
                        children: [
                          GestureDetector(
                            onTap: () =>
                                setState(() => _showPhotoPanel = true),
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
                                      onTap: () => _sendMessage(
                                          _messageController.text),
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

                // Кнопка назад в режиме просмотра
                if (_isReadOnly)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                    child: GestureDetector(
                      onTap: () => context.pop(),
                      child: Container(
                        width: double.infinity,
                        height: 48,
                        decoration: BoxDecoration(
                          color: const Color(0xFF2A2A2A),
                          borderRadius: BorderRadius.circular(33),
                        ),
                        child: const Center(
                          child: Text(
                            'Назад',
                            style: TextStyle(
                              fontFamily: 'Idiqlat',
                              fontSize: 18,
                              color: Colors.white,
                            ),
                          ),
                        ),
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

  Widget _buildMessage(ChatMessage message) {
    if (message.isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.75,
          ),
          margin: const EdgeInsets.only(bottom: 12),
          padding:
              const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
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

    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.9,
        ),
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
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
                      onTap: () {
                        setState(() => _showPhotoPanel = false);
                        // TODO: открыть камеру
                      },
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
                      onTap: () {
                        setState(() => _showPhotoPanel = false);
                        // TODO: открыть галерею
                      },
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