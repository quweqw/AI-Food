import 'package:ai_food/core/services/api_service.dart';
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
  late TextEditingController _currentPasswordController;
  late TextEditingController _newPasswordController;
  late TextEditingController _confirmPasswordController;
  bool _pushNotifications = true;
  bool _obscureCurrentPassword = true;
  bool _obscureNewPassword = true;
  bool _obscureConfirmPassword = true;

  @override
  void initState() {
    super.initState();
    final s = ref.read(settingsProvider);
    _currentPasswordController = TextEditingController();
    _newPasswordController = TextEditingController();
    _confirmPasswordController = TextEditingController();
    _pushNotifications = s.pushNotifications;
  }

  @override
  void dispose() {
    _currentPasswordController.dispose();
    _newPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final notifier = ref.read(settingsProvider.notifier);
    final currentPassword = _currentPasswordController.text;
    final newPassword = _newPasswordController.text;
    final confirmPassword = _confirmPasswordController.text;
    final wantsPasswordChange = currentPassword.isNotEmpty ||
        newPassword.isNotEmpty ||
        confirmPassword.isNotEmpty;

    if (wantsPasswordChange) {
      if (currentPassword.isEmpty ||
          newPassword.isEmpty ||
          confirmPassword.isEmpty) {
        _showMessage(
          'Заполните текущий пароль, новый пароль и повтор нового пароля',
        );
        return;
      }
      if (newPassword != confirmPassword) {
        _showMessage('Новые пароли не совпадают');
        return;
      }
      final passwordError = _passwordValidationError(newPassword);
      if (passwordError != null) {
        _showMessage(passwordError);
        return;
      }
    }

    notifier.updatePushNotifications(_pushNotifications);

    try {
      await apiService.saveSettings(ref.read(settingsProvider));
      if (wantsPasswordChange) {
        await apiService.changePassword(
          currentPassword: currentPassword,
          newPassword: newPassword,
          confirmPassword: confirmPassword,
        );
        _currentPasswordController.clear();
        _newPasswordController.clear();
        _confirmPasswordController.clear();
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              wantsPasswordChange ? 'Профиль и пароль сохранены' : 'Сохранено',
            ),
          ),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось сохранить профиль: $error')),
        );
      }
    }
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  String? _passwordValidationError(String password) {
    if (password.length < 8) return 'Пароль должен быть не короче 8 символов';
    if (!password.contains(RegExp(r'[A-Za-zА-Яа-я]'))) {
      return 'Пароль должен содержать букву';
    }
    if (!password.contains(RegExp(r'\d'))) {
      return 'Пароль должен содержать цифру';
    }
    if (!password.contains(RegExp(r'[A-ZА-Я]'))) {
      return 'Пароль должен содержать заглавную букву';
    }
    if (!password.contains(RegExp(r'[a-zа-я]'))) {
      return 'Пароль должен содержать строчную букву';
    }
    if (!password.contains(RegExp(r'[^A-Za-zА-Яа-я0-9]'))) {
      return 'Пароль должен содержать специальный символ';
    }
    return null;
  }

  void _logout() async {
    await apiService.logout();
    if (mounted) context.go('/');
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
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
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
                                  child: Text(
                                    settings.email,
                                    textAlign: TextAlign.right,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      fontFamily: 'Idiqlat',
                                      fontSize: 14,
                                      fontWeight: FontWeight.w900,
                                      color: Colors.white.withValues(alpha: 0.72),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Divider(
                              color: Colors.white.withValues(alpha: 0.08),
                              height: 1),

                          _buildPasswordField(
                            label: 'Используемый пароль',
                            controller: _currentPasswordController,
                            obscure: _obscureCurrentPassword,
                            onToggle: () => setState(
                              () => _obscureCurrentPassword =
                                  !_obscureCurrentPassword,
                            ),
                          ),
                          Divider(
                            color: Colors.white.withValues(alpha: 0.08),
                            height: 1,
                          ),
                          _buildPasswordField(
                            label: 'Новый пароль',
                            controller: _newPasswordController,
                            obscure: _obscureNewPassword,
                            onToggle: () => setState(
                              () => _obscureNewPassword = !_obscureNewPassword,
                            ),
                          ),
                          Divider(
                            color: Colors.white.withValues(alpha: 0.08),
                            height: 1,
                          ),
                          _buildPasswordField(
                            label: 'Новый пароль повторно',
                            controller: _confirmPasswordController,
                            obscure: _obscureConfirmPassword,
                            onToggle: () => setState(
                              () => _obscureConfirmPassword =
                                  !_obscureConfirmPassword,
                            ),
                          ),
                          Divider(
                            color: Colors.white.withValues(alpha: 0.08),
                            height: 1,
                          ),

                          // Push уведомления
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
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
                                      setState(() => _pushNotifications = val),
                                  activeThumbColor: Colors.green,
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
                      onTap: () => _save(),
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

  Widget _buildPasswordField({
    required String label,
    required TextEditingController controller,
    required bool obscure,
    required VoidCallback onToggle,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
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
          const SizedBox(height: 4),
          TextField(
            controller: controller,
            obscureText: obscure,
            style: const TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 14,
              color: Colors.white,
            ),
            decoration: InputDecoration(
              border: InputBorder.none,
              contentPadding: EdgeInsets.zero,
              hintText: 'Не менять',
              hintStyle: TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 14,
                color: Colors.white.withValues(alpha: 0.5),
              ),
              suffixIcon: IconButton(
                onPressed: onToggle,
                icon: Icon(
                  obscure ? Icons.visibility_off : Icons.visibility,
                  color: Colors.white54,
                  size: 18,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
