import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/core/providers/settings_provider.dart';

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  late TextEditingController _emailController;
  late TextEditingController _passwordController;
  bool _pushNotifications = true;
  bool _obscurePassword = true;

  @override
  void initState() {
    super.initState();
    final s = ref.read(settingsProvider);
    _emailController = TextEditingController(text: s.email);
    _passwordController = TextEditingController();
    _pushNotifications = s.pushNotifications;
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _save() {
    final notifier = ref.read(settingsProvider.notifier);
    notifier.updateEmail(_emailController.text.trim());
    notifier.updatePushNotifications(_pushNotifications);
    if (_passwordController.text.isNotEmpty) {
      notifier.updatePassword(_passwordController.text);
    }
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Сохранено')),
    );
  }

  void _logout() {
    context.go('/');
  }

  @override
  Widget build(BuildContext context) {
    final settings = ref.watch(settingsProvider);

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
                    'Settings',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: Color(0xFFE9E9E9),
                    ),
                  ),
                  GestureDetector(
                    onTap: () => context.pop(),
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
                  children: [
                    // Email пользователя
                    Text(
                      settings.email,
                      style: const TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 22,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 12),

                    // Кнопка редактировать — активная
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xFF303030),
                        border: Border.all(color: const Color(0xFF969696)),
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
                    const SizedBox(height: 24),

                    // АККАУНТ
                    Align(
                      alignment: Alignment.centerLeft,
                      child: const Text(
                        'АККАУНТ',
                        style: TextStyle(
                          fontFamily: 'Idiqlat',
                          fontSize: 13,
                          color: Colors.white,
                          letterSpacing: 1.2,
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Container(
                      decoration: BoxDecoration(
                        color: const Color(0xFF222222),
                        borderRadius: BorderRadius.circular(28),
                      ),
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      child: Column(
                        children: [
                          // Почта
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            child: Row(
                              children: [
                                const Text(
                                  'Почта',
                                  style: TextStyle(
                                    fontFamily: 'Idiqlat',
                                    fontSize: 16,
                                    color: Colors.white,
                                  ),
                                ),
                                const SizedBox(width: 16),
                                Expanded(
                                  child: TextField(
                                    controller: _emailController,
                                    keyboardType: TextInputType.emailAddress,
                                    textAlign: TextAlign.right,
                                    style: const TextStyle(
                                      fontFamily: 'Idiqlat',
                                      fontSize: 14,
                                      fontWeight: FontWeight.w900,
                                      color: Colors.white,
                                    ),
                                    decoration: const InputDecoration(
                                      border: InputBorder.none,
                                      contentPadding: EdgeInsets.zero,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Divider(
                              color: Colors.white.withOpacity(0.08),
                              height: 1),

                          // Пароль
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            child: Row(
                              mainAxisAlignment:
                                  MainAxisAlignment.spaceBetween,
                              children: [
                                const Text(
                                  'Пароль',
                                  style: TextStyle(
                                    fontFamily: 'Idiqlat',
                                    fontSize: 16,
                                    color: Colors.white,
                                  ),
                                ),
                                SizedBox(
                                  width: 180,
                                  child: TextField(
                                    controller: _passwordController,
                                    obscureText: _obscurePassword,
                                    textAlign: TextAlign.right,
                                    style: const TextStyle(
                                      fontFamily: 'Idiqlat',
                                      fontSize: 14,
                                      color: Colors.white,
                                    ),
                                    decoration: InputDecoration(
                                      border: InputBorder.none,
                                      contentPadding: EdgeInsets.zero,
                                      hintText: 'Изменить пароль',
                                      hintStyle: TextStyle(
                                        fontFamily: 'Idiqlat',
                                        fontSize: 14,
                                        color: Colors.white.withOpacity(0.5),
                                      ),
                                      suffixIcon: GestureDetector(
                                        onTap: () => setState(() =>
                                            _obscurePassword =
                                                !_obscurePassword),
                                        child: Icon(
                                          _obscurePassword
                                              ? Icons.visibility_off
                                              : Icons.visibility,
                                          color: Colors.white54,
                                          size: 18,
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Divider(
                              color: Colors.white.withOpacity(0.08),
                              height: 1),

                          // Push уведомления
                          Padding(
                            padding:
                                const EdgeInsets.symmetric(vertical: 12),
                            child: Row(
                              mainAxisAlignment:
                                  MainAxisAlignment.spaceBetween,
                              children: [
                                const Text(
                                  'Push-уведомления',
                                  style: TextStyle(
                                    fontFamily: 'Idiqlat',
                                    fontSize: 16,
                                    color: Colors.white,
                                  ),
                                ),
                                Switch(
                                  value: _pushNotifications,
                                  onChanged: (val) =>
                                      setState(() =>
                                          _pushNotifications = val),
                                  activeColor: Colors.green,
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 32),

                    // Сохранить
                    _buildActionButton(
                      label: 'Сохранить',
                      onTap: _save,
                      filled: true,
                    ),
                    const SizedBox(height: 12),

                    // Выйти
                    _buildActionButton(
                      label: 'Выйти',
                      onTap: _logout,
                      filled: false,
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

  Widget _buildActionButton({
    required String label,
    required VoidCallback onTap,
    required bool filled,
  }) {
    return SizedBox(
      width: double.infinity,
      height: 52,
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