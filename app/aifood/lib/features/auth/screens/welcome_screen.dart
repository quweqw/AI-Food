import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'dart:async';

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key});

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  final List<String> _phrases = [
    'Распознавание блюд',
    'Составление плана питания',
    'Подсчет калорий',
  ];

  int _currentIndex = 0;
  String _displayedText = '';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _startTyping();
  }

  void _startTyping() {
    final phrase = _phrases[_currentIndex];
    int charIndex = 0;

    _timer = Timer.periodic(const Duration(milliseconds: 60), (timer) {
      if (charIndex < phrase.length) {
        setState(() {
          _displayedText = phrase.substring(0, charIndex + 1);
        });
        charIndex++;
      } else {
        timer.cancel();
        // Пауза 3 секунды, потом стираем
        Future.delayed(const Duration(seconds: 3), () {
          _startErasing();
        });
      }
    });
  }

  void _startErasing() {
    final phrase = _phrases[_currentIndex];
    int charIndex = phrase.length;

    _timer = Timer.periodic(const Duration(milliseconds: 30), (timer) {
      if (charIndex > 0) {
        setState(() {
          _displayedText = phrase.substring(0, charIndex - 1);
        });
        charIndex--;
      } else {
        timer.cancel();
        setState(() {
          _currentIndex = (_currentIndex + 1) % _phrases.length;
        });
        Future.delayed(const Duration(milliseconds: 300), () {
          _startTyping();
        });
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      body: SafeArea(
        child: Stack(
          children: [
            // About — слева сверху
            Positioned(
              top: 16,
              left: 24,
              child: GestureDetector(
                onTap: () => context.push('/about'),
                child: const Text(
                  'About',
                  style: TextStyle(
                    fontFamily: 'Idiqlat',
                    fontSize: 22,
                    color: Color(0xFFB4B4B4),
                  ),
                ),
              ),
            ),

            // Contact — справа сверху
            Positioned(
              top: 16,
              right: 24,
              child: GestureDetector(
                onTap: () => context.push('/contact'),
                child: const Text(
                  'Contact',
                  style: TextStyle(
                    fontFamily: 'Idiqlat',
                    fontSize: 22,
                    color: Color(0xFFB4B4B4),
                  ),
                ),
              ),
            ),

            // Центр — название + анимация текста
            Positioned(
              top: 0,
              left: 0,
              right: 0,
              bottom: 502,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Text(
                    'AI Food',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 48,
                      fontWeight: FontWeight.w900,
                      color: Color(0xFFFFFFFF),
                    ),
                  ),
                  const SizedBox(height: 24),
                  SizedBox(
                    height: 32,
                    child: Text(
                      _displayedText,
                      style: const TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 20,
                        color: Color(0xFFD4D4D4),
                      ),
                    ),
                  ),
                ],
              ),
            ),

            // Нижняя панель с кнопками
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
                    // Кнопка Зарегистрироваться
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: ElevatedButton(
                        onPressed: () => context.push('/register'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF696969),
                          overlayColor: const Color(0xFF888888),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(44),
                          ),
                          elevation: 0,
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
                    const SizedBox(height: 16),
                    // Кнопка Войти
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: OutlinedButton(
                        onPressed: () => context.push('/login'),
                        style: OutlinedButton.styleFrom(
                          overlayColor: const Color(0xFF2F2F2F),
                          side: const BorderSide(
                            color: Color(0xFFE4E4E4),
                            width: 1.5,
                          ),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(44),
                          ),
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
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
