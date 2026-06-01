import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:ai_food/core/services/api_service.dart';
import 'package:ai_food/core/providers/settings_provider.dart';

class RegisterScreen extends ConsumerStatefulWidget {
  final String? initialEmail;
  final bool verifyOnly;

  const RegisterScreen({
    super.key,
    this.initialEmail,
    this.verifyOnly = false,
  });

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  final _codeController = TextEditingController();

  bool _obscurePassword = true;
  bool _obscureConfirm = true;
  bool _showVerification = false;

  @override
  void initState() {
    super.initState();
    _emailController.text = widget.initialEmail ?? '';
    _showVerification = widget.verifyOnly && _emailController.text.isNotEmpty;
    if (_emailController.text.isEmpty) {
      Future.microtask(_loadPendingVerification);
    }
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  void _register() async {
    final email = _emailController.text.trim();
    final password = _passwordController.text;
    final confirm = _confirmPasswordController.text;

    if (email.isEmpty || password.isEmpty || confirm.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Заполните все поля')),
      );
      return;
    }

    if (password != confirm) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Пароли не совпадают')),
      );
      return;
    }

    final passwordError = _passwordValidationError(password);
    if (passwordError != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(passwordError)),
      );
      return;
    }

    try {
      await apiService.register(email, password);
      await apiService.savePendingVerificationEmail(email);
      setState(() => _showVerification = true);
    } catch (e) {
      if (mounted) {
        final code = apiService.errorCode(e);
        if (code == 'EMAIL_NOT_VERIFIED') {
          final emailForVerification =
              apiService.errorDetails(e)['email']?.toString() ?? email;
          await apiService.savePendingVerificationEmail(emailForVerification);
          setState(() {
            _emailController.text = emailForVerification;
            _showVerification = true;
          });
          return;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка: $e')),
        );
      }
    }
  }

  void _verifyCode() async {
    final code = _codeController.text.trim();
    if (code.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Введите код')),
      );
      return;
    }
    if (!RegExp(r'^\d{6}$').hasMatch(code)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Код подтверждения должен состоять из 6 цифр')),
      );
      return;
    }

    try {
      final token = await apiService.verifyCode(
        _emailController.text.trim(), code,
      );
      await apiService.saveToken(token);

      final settingsData = await apiService.getSettings();
      if (mounted) {
        await ref.read(settingsProvider.notifier).loadFromBackend(settingsData);
        await apiService.clearPendingVerificationEmail();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Заполните параметры профиля')),
        );
        context.go('/settings?onboarding=1');
      }
    } catch (e) {
      if (mounted) {
        final code = apiService.errorCode(e);
        if (code == 'EMAIL_VERIFICATION_EXPIRED') {
          await apiService.clearPendingVerificationEmail();
          setState(() => _showVerification = false);
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
          const SnackBar(content: Text('Неверный код')),
        );
      }
    }
  }

  void _resendCode() async {
    try {
      await apiService.resendVerificationCode(_emailController.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Код отправлен повторно')),
        );
      }
    } catch (error) {
      if (mounted) {
        final code = apiService.errorCode(error);
        if (code == 'EMAIL_VERIFICATION_EXPIRED') {
          await apiService.clearPendingVerificationEmail();
          setState(() => _showVerification = false);
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
          SnackBar(content: Text('Не удалось отправить код: $error')),
        );
      }
    }
  }

  Future<void> _loadPendingVerification() async {
    final email = await apiService.getPendingVerificationEmail();
    if (!mounted || email == null) return;
    setState(() {
      _emailController.text = email;
      _showVerification = true;
    });
  }

  String? _passwordValidationError(String password) {
    if (password.length < 8) return 'Пароль должен быть не короче 8 символов';
    if (!password.contains(RegExp(r'[A-Za-zА-Яа-я]'))) {
      return 'В пароле должна быть хотя бы одна буква';
    }
    if (!password.contains(RegExp(r'\d'))) {
      return 'В пароле должна быть хотя бы одна цифра';
    }
    if (!password.contains(RegExp(r'[A-ZА-Я]'))) {
      return 'Добавьте заглавную букву';
    }
    if (!password.contains(RegExp(r'[a-zа-я]'))) {
      return 'Добавьте строчную букву';
    }
    if (!password.contains(RegExp(r'[^A-Za-zА-Яа-я0-9]'))) {
      return 'Добавьте специальный символ';
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final title = _showVerification ? 'Подтверждение' : 'Регистрация';

    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      resizeToAvoidBottomInset: true,
      body: SafeArea(
        child: Stack(
          children: [
            // AI Food — слева сверху
            Positioned(
              top: 16,
              left: 24,
              child: GestureDetector(
                onTap: () => _showVerification
                    ? context.go('/login')
                    : context.go('/'),
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

            // Заголовок
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

            // Нижняя панель
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
                child: _showVerification
                    ? _buildVerificationPanel()
                    : _buildRegistrationPanel(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // Панель регистрации
  Widget _buildRegistrationPanel() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        _buildFilledField(
          controller: _emailController,
          hint: 'Адрес электронной почты',
          keyboardType: TextInputType.emailAddress,
        ),
        const SizedBox(height: 12),
        _buildFilledField(
          controller: _passwordController,
          hint: 'Введите пароль',
          obscure: _obscurePassword,
          toggleObscure: () =>
              setState(() => _obscurePassword = !_obscurePassword),
        ),
        const SizedBox(height: 12),
        _buildFilledField(
          controller: _confirmPasswordController,
          hint: 'Введите пароль повторно',
          obscure: _obscureConfirm,
          toggleObscure: () =>
              setState(() => _obscureConfirm = !_obscureConfirm),
        ),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          height: 56,
          child: OutlinedButton(
            onPressed: _register,
            style: OutlinedButton.styleFrom(
              overlayColor: const Color(0xFF2F2F2F),
              side: const BorderSide(color: Color(0xFFE4E4E4), width: 1.5),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(44),
              ),
            ),
            child: const Text(
              'Зарегистрироваться',
              style: TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 20,
                fontWeight: FontWeight.w900,
                color: Color(0xFFFFFFFF),
              ),
            ),
          ),
        ),
      ],
    );
  }

  // Панель верификации
  Widget _buildVerificationPanel() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // Email (нередактируемый)
        SizedBox(
          height: 56,
          child: Container(
            decoration: BoxDecoration(
              color: const Color(0xFF696969),
              borderRadius: BorderRadius.circular(44),
            ),
            alignment: Alignment.centerLeft,
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              _emailController.text,
              style: const TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 18,
                fontWeight: FontWeight.w900,
                color: Color(0xFFFFFFFF),
              ),
            ),
          ),
        ),
        const SizedBox(height: 12),

        // Поле кода
        _buildFilledField(
          controller: _codeController,
          hint: '6-значный код из письма',
          keyboardType: TextInputType.number,
        ),
        const SizedBox(height: 16),

        // Кнопка подтверждения
        SizedBox(
          width: double.infinity,
          height: 56,
          child: OutlinedButton(
            onPressed: _verifyCode,
            style: OutlinedButton.styleFrom(
              overlayColor: const Color(0xFF2F2F2F),
              side: const BorderSide(color: Color(0xFFE4E4E4), width: 1.5),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(44),
              ),
            ),
            child: const Text(
              'Подтвердить',
              style: TextStyle(
                fontFamily: 'Idiqlat',
                fontSize: 20,
                fontWeight: FontWeight.w900,
                color: Color(0xFFFFFFFF),
              ),
            ),
          ),
        ),
        const SizedBox(height: 12),

        // Отправить повторно
        GestureDetector(
          onTap: _resendCode,
          child: const Text(
            'Отправить код повторно',
            style: TextStyle(
              fontFamily: 'Idiqlat',
              fontSize: 16,
              color: Color(0xFFFFFFFF),
              decoration: TextDecoration.underline,
              decorationColor: Color(0xFFFFFFFF),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildFilledField({
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
          filled: true,
          fillColor: const Color(0xFF696969),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(44),
            borderSide: BorderSide.none,
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
