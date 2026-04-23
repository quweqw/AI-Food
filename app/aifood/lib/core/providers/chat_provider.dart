import 'package:flutter_riverpod/flutter_riverpod.dart';

class ChatMessage {
  final String text;
  final bool isUser;

  ChatMessage({required this.text, required this.isUser});
}

class Chat {
  final String id;
  final List<ChatMessage> messages;

  Chat({required this.id, required this.messages});

  String get title {
    final first = messages.firstWhere(
      (m) => m.isUser,
      orElse: () => ChatMessage(text: 'Чат', isUser: true),
    );
    final text = first.text;
    return text.length > 40 ? '${text.substring(0, 40)}...' : text;
  }
}

class ChatNotifier extends StateNotifier<List<Chat>> {
  ChatNotifier() : super([]);

  String _currentChatId = _generateId();

  static String _generateId() =>
      DateTime.now().millisecondsSinceEpoch.toString();

  String get currentChatId => _currentChatId;

  // Добавить сообщение в текущий чат
  void addMessage(ChatMessage message) {
    final existing = state.indexWhere((c) => c.id == _currentChatId);
    if (existing == -1) {
      state = [
        ...state,
        Chat(id: _currentChatId, messages: [message]),
      ];
    } else {
      state = [
        for (final chat in state)
          if (chat.id == _currentChatId)
            Chat(
              id: chat.id,
              messages: [...chat.messages, message],
            )
          else
            chat,
      ];
    }
  }

  // Создать новый чат
  void newChat() {
    _currentChatId = _generateId();
  }

  // Получить текущий чат
  Chat? get currentChat {
    try {
      return state.firstWhere((c) => c.id == _currentChatId);
    } catch (_) {
      return null;
    }
  }

  // Получить чат по id
  Chat? getChatById(String id) {
    try {
      return state.firstWhere((c) => c.id == id);
    } catch (_) {
      return null;
    }
  }

  // История — все чаты кроме пустых, от новых к старым
  List<Chat> get history =>
    state.where((c) => c.messages.isNotEmpty).toList().reversed.toList();
}

final chatProvider = StateNotifierProvider<ChatNotifier, List<Chat>>(
  (ref) => ChatNotifier(),
);