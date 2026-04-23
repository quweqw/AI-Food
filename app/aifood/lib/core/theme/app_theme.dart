import 'package:flutter/material.dart';
import 'app_colors.dart';

class AppTheme {
  static ThemeData get dark => ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: AppColors.background,
    fontFamily: 'Idiqlat',
    colorScheme: const ColorScheme.dark(
      surface: AppColors.panel,
    ),
    textTheme: const TextTheme(
      displayLarge: TextStyle(
        color: AppColors.textPrimary,
        fontSize: 36,
        fontWeight: FontWeight.w900,
      ),
      bodyLarge: TextStyle(
        color: AppColors.textPrimary,
        fontSize: 18,
      ),
      bodyMedium: TextStyle(
        color: AppColors.textPrimary,
        fontSize: 16,
      ),
    ),
  );
}