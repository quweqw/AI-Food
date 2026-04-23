import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _obscurePassword = true;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _login() {
    final email = _emailController.text.trim();
    final password = _passwordController.text;

    if (email.isEmpty || password.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Заполните все поля')),
      );
      return;
    }

    // TODO: подключить к backend
    context.go('/chat');
  }

  void _forgotPassword() {
    // TODO: экран восстановления пароля
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Письмо для восстановления отправлено')),
    );
  }

  @override
  Widget build(BuildContext context) {
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

            // Заголовок
            const Positioned(
              top: 80,
              left: 0,
              right: 0,
              child: Center(
                child: Text(
                  'Вход',
                  style: TextStyle(
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
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Email — outline стиль
                    _buildOutlineField(
                      controller: _emailController,
                      hint: 'Адрес электронной почты',
                      keyboardType: TextInputType.emailAddress,
                    ),
                    const SizedBox(height: 12),

                    // Пароль — outline стиль
                    _buildOutlineField(
                      controller: _passwordController,
                      hint: 'Введите пароль',
                      obscure: _obscurePassword,
                      toggleObscure: () => setState(
                        () => _obscurePassword = !_obscurePassword,
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Кнопка Войти — filled
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: ElevatedButton(
                        onPressed: _login,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF696969),
                          overlayColor: const Color(0xFF888888),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(44),
                          ),
                          elevation: 0,
                        ),
                        child: const Text(
                          'Войти',
                          style: TextStyle(
                            fontFamily: 'Idiqlat',
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                            color: Color(0xFFFFFFFF),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Забыли пароль
                    GestureDetector(
                      onTap: _forgotPassword,
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
                  ],
                ),
              ),
            ),
          ],
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