import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class AboutScreen extends StatelessWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF151515),
      body: SafeArea(
        child: Stack(
          children: [
            // Назад — справа сверху
            Positioned(
              top: 16,
              right: 24,
              child: GestureDetector(
                onTap: () => context.pop(),
                child: const Text(
                  'Назад',
                  style: TextStyle(
                    fontFamily: 'Idiqlat',
                    fontSize: 22,
                    color: Color(0xFFB4B4B4),
                  ),
                ),
              ),
            ),

            // Контент
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 80, 24, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  // Название
                  const Text(
                    'AI Food',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 36,
                      fontWeight: FontWeight.w900,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: 24),

                  // Описание
                  const Text(
                    'Приложение для распознавания еды, подсчёта калорий и составления персонального питания.',
                    style: TextStyle(
                      fontFamily: 'Idiqlat',
                      fontSize: 16,
                      color: Color(0xFFD4D4D4),
                      height: 1.6,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),

                  // Технологии
                  RichText(
                    textAlign: TextAlign.center,
                    text: const TextSpan(
                      style: TextStyle(
                        fontFamily: 'Idiqlat',
                        fontSize: 16,
                        color: Color(0xFFD4D4D4),
                        height: 1.6,
                      ),
                      children: [
                        TextSpan(text: 'Использует '),
                        TextSpan(
                          text: 'YOLO & CLIP + FAISS',
                          style: TextStyle(
                            fontWeight: FontWeight.w900,
                            color: Colors.white,
                          ),
                        ),
                        TextSpan(text: ' для изображений и '),
                        TextSpan(
                          text: 'LLaMA 3.1 (8B)',
                          style: TextStyle(
                            fontWeight: FontWeight.w900,
                            color: Colors.white,
                          ),
                        ),
                        TextSpan(text: ' для генерации.'),
                      ],
                    ),
                  ),
                ],
              ),
            ),

            // Кнопки внизу — такие же как на Welcome
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
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: ElevatedButton(
                        onPressed: () => context.go('/register'),
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
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: OutlinedButton(
                        onPressed: () => context.go('/login'),
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
                            color: Colors.white,
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