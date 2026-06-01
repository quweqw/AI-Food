import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/core/services/api_service.dart';
import 'package:ai_food/core/providers/settings_provider.dart';

enum _LoginMode { login, resetEmail, resetCode }

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _resetEmailController = TextEditingController();
  final _resetCodeController = TextEditingController();
  final _resetNewPasswordController = TextEditingController();
  final _resetConfirmPasswordController = TextEditingController();
  _LoginMode _mode = _LoginMode.login;
  bool _obscurePassword = true;
  bool _obscureResetNewPassword = true;
  bool _obscureResetConfirmPassword = true;
  bool _isBusy = false;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _resetEmailController.dispose();
    _resetCodeController.dispose();
    _resetNewPasswordController.dispose();
    _resetConfirmPasswordController.dispose();
    super.dispose();
  }

  void _login() async {
    final email = _emailController.text.trim();
    final password = _passwordController.text;

    if (email.isEmpty || password.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Заполните все поля')),
      );
      return;
    }

    setState(() => _isBusy = true);
    try {
      final token = await apiService.login(email, password);
      await apiService.saveToken(token);
      await apiService.clearPendingVerificationEmail();

      final settingsData = await apiService.getSettings();
      if (mounted) {
        ref.read(settingsProvider.notifier).loadFromBackend(settingsData);
        context.go('/chat');
      }
    } catch (e) {
      if (mounted) {
        final code = apiService.errorCode(e);
        if (code == 'EMAIL_NOT_VERIFIED') {
          final emailForVerification =
              apiService.errorDetails(e)['email']?.toString() ?? email;
          await apiService.savePendingVerificationEmail(emailForVerification);
          if (mounted) {
            context.go(
              '/register?verify=1&email=${Uri.encodeComponent(emailForVerification)}',
            );
          }
          return;
        }
        if (code == 'EMAIL_VERIFICATION_EXPIRED') {
          await apiService.clearPendingVerificationEmail();
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'Срок подтверждения истёк. Зарегистрируйтесь заново.',
              ),
            ),
          );
          return;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Неверный email или пароль')),
        );
      }
    } finally {
      if (mounted) setState(() => _isBusy = false);
    }
  }

  void _forgotPassword() {
    _resetEmailController.text = _emailController.text.trim();
    setState(() {
      _mode = _LoginMode.resetEmail;
    });
  }

  Future<void> _requestPasswordReset() async {
    final email = _resetEmailController.text.trim();
    if (email.isEmpty) {
      _showMessage('Введите email');
      return;
    }

    setState(() => _isBusy = true);
    try {
      await apiService.requestPasswordReset(email);
      if (!mounted) return;
      setState(() {
        _mode = _LoginMode.resetCode;
      });
      _showMessage('Код восстановления отправлен на email');
    } catch (error) {
      _showMessage('Не удалось отправить код восстановления');
    } finally {
      if (mounted) setState(() => _isBusy = false);
    }
  }

  Future<void> _resetPassword() async {
    final email = _resetEmailController.text.trim();
    final code = _resetCodeController.text.trim();
    final newPassword = _resetNewPasswordController.text;
    final confirmPassword = _resetConfirmPasswordController.text;

    if (email.isEmpty ||
        code.isEmpty ||
        newPassword.isEmpty ||
        confirmPassword.isEmpty) {
      _showMessage('Заполните email, код и новый пароль');
      return;
    }
    if (!RegExp(r'^\d{8}$').hasMatch(code)) {
      _showMessage('Код восстановления должен состоять из 8 цифр');
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

    setState(() => _isBusy = true);
    try {
      await apiService.resetPassword(
        email: email,
        code: code,
        newPassword: newPassword,
        confirmPassword: confirmPassword,
      );
      if (!mounted) return;
      _emailController.text = email;
      _passwordController.clear();
      _resetCodeController.clear();
      _resetNewPasswordController.clear();
      _resetConfirmPasswordController.clear();
      await apiService.clearPendingVerificationEmail();
      setState(() {
        _mode = _LoginMode.login;
      });
      _showMessage('Пароль обновлён. Теперь войдите с новым паролем.');
    } catch (error) {
      _showMessage('Не удалось обновить пароль. Проверьте код и пароль.');
    } finally {
      if (mounted) setState(() => _isBusy = false);
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

  @override
  Widget build(BuildContext context) {
    final title = switch (_mode) {
      _LoginMode.login => 'Вход',
      _LoginMode.resetEmail => 'Восстановление',
      _LoginMode.resetCode => 'Новый пароль',
    };

    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      resizeToAvoidBottomInset: true,
      body: SafeArea(
        child: Stack(
          children: [
            Positioned(
              top: 16,
              left: 24,
              child: GestureDetector(
                onTap: () => context.go('/'),
                child: const Text(
                  'AI Food',
                  style: TextStyle(
                    fontFamily: 'Idiqlat',
                    fontSize: 22,
                    color: Color(0xFFB4B4B4),
                  ),
                ),
              ),
            ),
            Positioned(
              top: 80,
              left: 0,
              right: 0,
              child: Center(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontFamily: 'Idiqlat',
                    fontSize: 36,
                    fontWeight: FontWeight.w900,
                    color: Color(0xFFFFFFFF),
                  ),
                ),
              ),
            ),
            Align(
              alignment: Alignment.bottomCenter,
              child: Container(
                width: double.infinity,
                decoration: const BoxDecoration(
                  color: Color(0xFF2A2A2A),
                  borderRadius: BorderRadius.only(
                    topLeft: Radius.circular(53),
                    topRight: Radius.circular(53),
                  ),
                ),
                padding: const EdgeInsets.fromLTRB(24, 32, 24, 48),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: _mode == _LoginMode.login
                      ? _buildLoginForm()
                      : _buildPasswordResetForm(),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildLoginForm() {
    return [
      _buildOutlineField(
        controller: _emailController,
        hint: 'Адрес электронной почты',
        keyboardType: TextInputType.emailAddress,
      ),
      const SizedBox(height: 12),
      _buildOutlineField(
        controller: _passwordController,
        hint: 'Введите пароль',
        obscure: _obscurePassword,
        toggleObscure: () => setState(
          () => _obscurePassword = !_obscurePassword,
        ),
      ),
      const SizedBox(height: 16),
      _buildPrimaryButton(
        label: _isBusy ? 'Входим...' : 'Войти',
        onPressed: _isBusy ? null : _login,
      ),
      const SizedBox(height: 16),
      GestureDetector(
        onTap: _isBusy ? null : _forgotPassword,
        child: const Text(
          'Забыли пароль?',
          style: TextStyle(
            fontFamily: 'Idiqlat',
            fontSize: 16,
            fontWeight: FontWeight.w900,
            color: Color(0xFFFFFFFF),
            decoration: TextDecoration.underline,
            decorationColor: Color(0xFFFFFFFF),
          ),
        ),
      ),
    ];
  }

  List<Widget> _buildPasswordResetForm() {
    if (_mode == _LoginMode.resetEmail) {
      return [
        _buildOutlineField(
          controller: _resetEmailController,
          hint: 'Email для восстановления',
          keyboardType: TextInputType.emailAddress,
        ),
        const SizedBox(height: 16),
        _buildPrimaryButton(
          label: _isBusy ? 'Отправляем...' : 'Получить 8-значный код',
          onPressed: _isBusy ? null : _requestPasswordReset,
        ),
        const SizedBox(height: 16),
        _buildTextAction(
          label: 'Вернуться ко входу',
          onTap: () => setState(() => _mode = _LoginMode.login),
        ),
      ];
    }

    return [
      _buildOutlineField(
        controller: _resetEmailController,
        hint: 'Email',
        keyboardType: TextInputType.emailAddress,
      ),
      const SizedBox(height: 12),
      _buildOutlineField(
        controller: _resetCodeController,
        hint: '8-значный код',
        keyboardType: TextInputType.number,
      ),
      const SizedBox(height: 12),
      _buildOutlineField(
        controller: _resetNewPasswordController,
        hint: 'Новый пароль',
        obscure: _obscureResetNewPassword,
        toggleObscure: () => setState(
          () => _obscureResetNewPassword = !_obscureResetNewPassword,
        ),
      ),
      const SizedBox(height: 12),
      _buildOutlineField(
        controller: _resetConfirmPasswordController,
        hint: 'Новый пароль повторно',
        obscure: _obscureResetConfirmPassword,
        toggleObscure: () => setState(
          () => _obscureResetConfirmPassword = !_obscureResetConfirmPassword,
        ),
      ),
      const SizedBox(height: 16),
      _buildPrimaryButton(
        label: _isBusy ? 'Обновляем...' : 'Обновить пароль',
        onPressed: _isBusy ? null : _resetPassword,
      ),
      const SizedBox(height: 16),
      Wrap(
        alignment: WrapAlignment.center,
        spacing: 18,
        runSpacing: 10,
        children: [
          _buildTextAction(
            label: 'Отправить код ещё раз',
            onTap: _isBusy ? null : _requestPasswordReset,
          ),
          _buildTextAction(
            label: 'Вход',
            onTap: () => setState(() => _mode = _LoginMode.login),
          ),
        ],
      ),
    ];
  }

  Widget _buildPrimaryButton({
    required String label,
    required VoidCallback? onPressed,
  }) {
    return SizedBox(
      width: double.infinity,
      height: 56,
      child: ElevatedButton(
        onPressed: onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: const Color(0xFF696969),
          disabledBackgroundColor: const Color(0xFF4C4C4C),
          overlayColor: const Color(0xFF888888),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(44),
          ),
          elevation: 0,
        ),
        child: Text(
          label,
          style: const TextStyle(
            fontFamily: 'Idiqlat',
            fontSize: 20,
            fontWeight: FontWeight.w900,
            color: Color(0xFFFFFFFF),
          ),
        ),
      ),
    );
  }

  Widget _buildTextAction({
    required String label,
    required VoidCallback? onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Text(
        label,
        style: TextStyle(
          fontFamily: 'Idiqlat',
          fontSize: 16,
          fontWeight: FontWeight.w900,
          color: onTap == null
              ? const Color(0xFFFFFFFF).withValues(alpha: 0.42)
              : const Color(0xFFFFFFFF),
          decoration: TextDecoration.underline,
          decorationColor: onTap == null
              ? const Color(0xFFFFFFFF).withValues(alpha: 0.42)
              : const Color(0xFFFFFFFF),
        ),
      ),
    );
  }

  Widget _buildOutlineField({
    required TextEditingController controller,
    required String hint,
    bool obscure = false,
    VoidCallback? toggleObscure,
    TextInputType keyboardType = TextInputType.text,
  }) {
    return SizedBox(
      height: 56,
      child: TextField(
        controller: controller,
        obscureText: obscure,
        keyboardType: keyboardType,
        style: const TextStyle(
          fontFamily: 'Idiqlat',
          fontSize: 18,
          fontWeight: FontWeight.w900,
          color: Color(0xFFFFFFFF),
        ),
        decoration: InputDecoration(
          hintText: hint,
          hintStyle: const TextStyle(
            fontFamily: 'Idiqlat',
            fontSize: 18,
            fontWeight: FontWeight.w900,
            color: Color(0xFFFFFFFF),
          ),
          filled: false,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(44),
            borderSide: const BorderSide(
              color: Color(0xFFE4E4E4),
              width: 1.5,
            ),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(44),
            borderSide: const BorderSide(
              color: Color(0xFFE4E4E4),
              width: 1.5,
            ),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(44),
            borderSide: const BorderSide(
              color: Color(0xFFFFFFFF),
              width: 1.5,
            ),
          ),
          contentPadding: const EdgeInsets.symmetric(horizontal: 24),
          suffixIcon: toggleObscure != null
              ? IconButton(
                  icon: Icon(
                    obscure ? Icons.visibility_off : Icons.visibility,
                    color: const Color(0xFFFFFFFF),
                  ),
                  onPressed: toggleObscure,
                )
              : null,
        ),
      ),
    );
  }
}
