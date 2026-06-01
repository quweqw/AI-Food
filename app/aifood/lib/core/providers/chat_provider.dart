import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

String _fallbackChatId() => DateTime.now().microsecondsSinceEpoch.toString();

class ChatMessage {
  final String text;
  final bool isUser;
  final bool isLoading;
  final String kind;
  final Uint8List? imageBytes;
  final Map<String, dynamic>? metadata;

  ChatMessage({
    required this.text,
    required this.isUser,
    this.isLoading = false,
    this.kind = 'text',
    this.imageBytes,
    this.metadata,
  });

  Map<String, dynamic> toJson() => {
        'text': text,
        'isUser': isUser,
        'isLoading': false,
        'kind': imageBytes == null ? kind : 'text',
        'metadata': imageBytes == null ? metadata : null,
      };

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        text: json['text']?.toString() ?? '',
        isUser: json['isUser'] == true,
        isLoading: false,
        kind: json['kind']?.toString() ?? 'text',
        metadata: json['metadata'] is Map
            ? Map<String, dynamic>.from(json['metadata'])
            : null,
      );
}

class Chat {
  final String id;
  final List<ChatMessage> messages;

  Chat({required this.id, required this.messages});

  Map<String, dynamic> toJson() => {
        'id': id,
        'messages': messages
            .where((message) => !message.isLoading)
            .map((message) => message.toJson())
            .toList(),
      };

  factory Chat.fromJson(Map<String, dynamic> json) => Chat(
        id: json['id']?.toString() ?? _fallbackChatId(),
        messages: (json['messages'] as List? ?? const [])
            .whereType<Map>()
            .map((item) => ChatMessage.fromJson(Map<String, dynamic>.from(item)))
            .toList(),
      );

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

  static const _historyKey = 'ai_food_chat_history_v1';
  bool _loaded = false;
  String _currentChatId = _generateId();

  static String _generateId() =>
      DateTime.now().millisecondsSinceEpoch.toString();

  String get currentChatId => _currentChatId;

  Future<void> loadHistory() async {
    if (_loaded) return;
    _loaded = true;
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_historyKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final decoded = jsonDecode(raw) as List;
      final chats = decoded
          .whereType<Map>()
          .map((item) => Chat.fromJson(Map<String, dynamic>.from(item)))
          .where((chat) => chat.messages.isNotEmpty)
          .toList();
      if (chats.isNotEmpty) {
        state = chats;
        _currentChatId = chats.last.id;
      }
    } catch (_) {
      await prefs.remove(_historyKey);
    }
  }

  Future<void> _persist() async {
    final prefs = await SharedPreferences.getInstance();
    final cleanHistory = state
        .where((chat) => chat.messages.isNotEmpty)
        .map((chat) => chat.toJson())
        .toList();
    await prefs.setString(_historyKey, jsonEncode(cleanHistory));
  }

  // Добавить сообщение в текущий чат
  void addMessage(ChatMessage message) {
    final existing = state.indexWhere((c) => c.id == _currentChatId);
    if (existing == -1) {
      state = [
        ...state,
        Chat(id: _currentChatId, messages: [message]),
      ];
    } else {
      final current = state[existing];
      final updated = Chat(
        id: current.id,
        messages: [...current.messages, message],
      );
      state = [
        for (final chat in state)
          if (chat.id != _currentChatId) chat,
        updated,
      ];
    }
    _persist();
  }

  void updateLastMessage(String text) {
    replaceLastMessage(ChatMessage(text: text, isUser: false));
  }

  void replaceLastMessage(ChatMessage message) {
    final chatIndex = state.indexWhere((c) => c.id == _currentChatId);
    if (chatIndex == -1) return;

    final chat = state[chatIndex];
    if (chat.messages.isEmpty) return;

    final updatedMessages = List<ChatMessage>.from(chat.messages);
    updatedMessages[updatedMessages.length - 1] = message;

    state = [
      for (int i = 0; i < state.length; i++)
        if (i == chatIndex)
          Chat(id: chat.id, messages: updatedMessages)
        else
          state[i],
    ];
    _persist();
  }

  // Создать новый чат
  void newChat() {
    _currentChatId = _generateId();
    state = [...state];
  }

  void openChat(String id) {
    if (state.any((chat) => chat.id == id)) {
      _currentChatId = id;
      state = [...state];
    }
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
