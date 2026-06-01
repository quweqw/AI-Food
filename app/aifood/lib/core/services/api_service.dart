import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:ai_food/core/providers/settings_provider.dart';
import 'package:ai_food/features/meal_planner/models/meal_plan_models.dart';

class ApiService {
  static const String baseUrl = 'http://localhost:8000';
  static const String _pendingVerificationEmailKey =
      'pending_verification_email';

  final Dio _dio;
  final FlutterSecureStorage _storage;

  ApiService()
      : _dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 45),
        )),
        _storage = const FlutterSecureStorage() {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _storage.read(key: 'access_token');
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (error, handler) async {
          final statusCode = error.response?.statusCode;
          final path = error.requestOptions.path;
          if (statusCode == 401 && path != '/auth/refresh') {
            final refreshed = await _tryRefreshToken();
            if (refreshed) {
              final token = await _storage.read(key: 'access_token');
              final options = error.requestOptions;
              options.headers['Authorization'] = 'Bearer $token';
              try {
                final retry = await _dio.fetch(options);
                handler.resolve(retry);
                return;
              } catch (_) {
                // Fall through to the original error.
              }
            }
          }
          handler.next(error);
        },
      ),
    );
  }

  Future<bool> _tryRefreshToken() async {
    final refreshToken = await _storage.read(key: 'refresh_token');
    if (refreshToken == null) return false;
    try {
      final response = await _dio.post(
        '/auth/refresh',
        data: {'refresh_token': refreshToken},
        options: Options(headers: {'Content-Type': 'application/json'}),
      );
      await saveTokens(
        response.data['access_token'].toString(),
        response.data['refresh_token'].toString(),
      );
      return true;
    } catch (_) {
      await deleteToken();
      return false;
    }
  }

  Future<void> saveToken(String token) async {
    await _storage.write(key: 'access_token', value: token);
  }

  Future<void> saveTokens(String accessToken, String refreshToken) async {
    await _storage.write(key: 'access_token', value: accessToken);
    await _storage.write(key: 'refresh_token', value: refreshToken);
  }

  Future<void> deleteToken() async {
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'refresh_token');
  }

  Future<bool> isLoggedIn() async {
    final token = await _storage.read(key: 'access_token');
    return token != null;
  }

  Future<void> savePendingVerificationEmail(String email) async {
    await _storage.write(
      key: _pendingVerificationEmailKey,
      value: email.trim(),
    );
  }

  Future<String?> getPendingVerificationEmail() async {
    final email = await _storage.read(key: _pendingVerificationEmailKey);
    if (email == null || email.trim().isEmpty) return null;
    return email.trim();
  }

  Future<void> clearPendingVerificationEmail() async {
    await _storage.delete(key: _pendingVerificationEmailKey);
  }

  String? errorCode(Object error) {
    if (error is! DioException) return null;
    final data = error.response?.data;
    if (data is Map && data['detail'] is Map) {
      final detail = Map<String, dynamic>.from(data['detail'] as Map);
      if (detail['error'] is Map) {
        return Map<String, dynamic>.from(detail['error'] as Map)['code']
            ?.toString();
      }
    }
    return null;
  }

  Map<String, dynamic> errorDetails(Object error) {
    if (error is! DioException) return const {};
    final data = error.response?.data;
    if (data is Map && data['detail'] is Map) {
      final detail = Map<String, dynamic>.from(data['detail'] as Map);
      if (detail['error'] is Map) {
        final errorBody = Map<String, dynamic>.from(detail['error'] as Map);
        if (errorBody['details'] is Map) {
          return Map<String, dynamic>.from(errorBody['details'] as Map);
        }
      }
    }
    return const {};
  }

  // ─── AUTH ─────────────────────────────────────────────────────────────────

  Future<void> register(String email, String password) async {
    await _dio.post(
      '/auth/register',
      data: {
        'email': email,
        'password': password,
        'confirm_password': password,
      },
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
  }

  Future<void> resendVerificationCode(String email) async {
    await _dio.post(
      '/auth/resend-verification-code',
      data: {'email': email},
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
  }

  Future<String> verifyCode(String email, String code) async {
    final response = await _dio.post(
      '/auth/verify-email',
      data: {'email': email, 'code': code},
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
    final refreshToken = response.data['refresh_token']?.toString();
    if (refreshToken != null) {
      await saveTokens(response.data['access_token'].toString(), refreshToken);
    }
    return response.data['access_token'];
  }

  Future<String> login(String email, String password) async {
    final response = await _dio.post(
      '/auth/login',
      data: {'email': email, 'password': password},
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
    final refreshToken = response.data['refresh_token']?.toString();
    if (refreshToken != null) {
      await saveTokens(response.data['access_token'].toString(), refreshToken);
    }
    return response.data['access_token'];
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
    required String confirmPassword,
  }) async {
    await _dio.post(
      '/auth/change-password',
      data: {
        'current_password': currentPassword,
        'new_password': newPassword,
        'confirm_password': confirmPassword,
      },
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
  }

  Future<void> requestPasswordReset(String email) async {
    await _dio.post(
      '/auth/password-reset/request',
      data: {'email': email},
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
  }

  Future<void> resetPassword({
    required String email,
    required String code,
    required String newPassword,
    required String confirmPassword,
  }) async {
    await _dio.post(
      '/auth/password-reset/confirm',
      data: {
        'email': email,
        'code': code,
        'new_password': newPassword,
        'confirm_password': confirmPassword,
      },
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
  }

  Future<void> logout() async {
    try {
      await _dio.post('/auth/logout');
    } finally {
      await deleteToken();
    }
  }

  Future<Map<String, dynamic>> me() async {
    final response = await _dio.get('/auth/me');
    return Map<String, dynamic>.from(response.data);
  }

  // ─── CHAT STREAMING ───────────────────────────────────────────────────────

  Stream<String> chatStream({
    required String message,
    List<Map<String, String>> history = const [],
    required List<String> allergens,
    required List<String> favoriteProducts,
    required List<String> dislikedProducts,
    required List<String> excludedProducts,
    required int dailyCalories,
    required String dietType,
    required int age,
    required String gender,
    required int height,
    required double weight,
  }) async* {
    final token = await _storage.read(key: 'access_token');

    try {
      final response = await _dio.post(
        '/chat/message',
        data: {
          'message': message,
          'history': history,
          'allergens': allergens,
          'favorite_products': favoriteProducts,
          'disliked_products': dislikedProducts,
          'excluded_products': excludedProducts,
          'daily_calories': dailyCalories,
          'diet_type': dietType,
          'age': age,
          'gender': gender,
          'height': height,
          'weight': weight,
        },
        options: Options(
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $token',
          },
          receiveTimeout: const Duration(seconds: 120),
        ),
      );

      final text = response.data['response'] as String? ?? '';

      // Имитируем стриминг посимвольно
      for (int i = 0; i < text.length; i++) {
        yield text[i];
        await Future.delayed(const Duration(milliseconds: 10));
      }
    } catch (e) {
      yield 'Ошибка: $e';
    }
  }

  // ─── RECOGNITION ──────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> recognizeImage({
    required List<int> imageBytes,
    required String filename,
    required UserSettings settings,
  }) async {
    final goalMap = {
      DietType.bulk: 'bulk',
      DietType.cut: 'cut',
      DietType.normal: 'normal',
    };

    final formData = FormData.fromMap({
      'file': MultipartFile.fromBytes(imageBytes, filename: filename),
      'age': settings.age,
      'gender': settings.gender == Gender.male ? 'male' : 'female',
      'height': settings.height,
      'weight': settings.weight,
      'diet_type': goalMap[settings.dietType] ?? 'normal',
      'daily_calories': settings.dailyCalories,
      'allergens': settings.allergens.join(','),
      'excluded_products': settings.excludedProducts.join(','),
      'favorite_products': settings.favoriteProducts.join(','),
      'disliked_products': settings.dislikedProducts.join(','),
    });

    // Убираем явный Content-Type — dio сам поставит multipart с boundary
    final response = await _dio.post(
      '/recognition/image',
      data: formData,
    );
    return response.data;
  }
  // ─── SETTINGS ─────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getSettings() async {
    final response = await _dio.get('/profile');
    return Map<String, dynamic>.from(response.data['profile'] ?? response.data);
  }

  Future<void> saveSettings(UserSettings settings) async {
    final goalMap = {
      DietType.bulk: 'bulk',
      DietType.cut: 'cut',
      DietType.normal: 'normal',
    };

    await _dio.put(
      '/profile',
      data: {
        'name': settings.name,
        'age': settings.age,
        'sex': settings.gender == Gender.male ? 'male' : 'female',
        'height_cm': settings.height,
        'weight_kg': settings.weight,
        'activity_level': settings.activityLevel,
        'target_calories': settings.dailyCalories,
        'goal': goalForSettings(settings),
        'diet_type': goalMap[settings.dietType] ?? 'normal',
        'meals_per_day': settings.mealsPerDay,
        'allergies': settings.allergens,
        'preferred_ingredients': settings.favoriteProducts,
        'disliked_ingredients': settings.dislikedProducts,
        'excluded_ingredients': settings.excludedProducts,
        'push_notifications': settings.pushNotifications,
      },
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
  }

  Future<Map<String, dynamic>> calculateCalories(UserSettings settings) async {
    final response = await _dio.post(
      '/profile/calculate-calories',
      data: {
        'sex': settings.gender == Gender.male ? 'male' : 'female',
        'age': settings.age,
        'height_cm': settings.height,
        'weight_kg': settings.weight,
        'activity_level': settings.activityLevel,
        'goal': goalForSettings(settings),
      },
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
    return Map<String, dynamic>.from(response.data);
  }

  // ─── MEAL PLANNER ───────────────────────────────────────────────────────

  Future<MealPlannerIntentResult> parseMealPlannerIntent(
    String message,
    UserSettings settings,
  ) async {
    final response = await _dio.post(
      '/meal-planner/intent/parse',
      data: {
        'message': message,
        'current_profile': {
          'target_calories': settings.dailyCalories,
          'daily_calories': settings.dailyCalories,
          'goal': goalForSettings(settings),
          'diet_type': dietTypeForSettings(settings),
          'meals_per_day': settings.mealsPerDay,
          'allergies': settings.allergens,
          'excluded': settings.excludedProducts,
          'preferred': settings.favoriteProducts,
          'disliked': settings.dislikedProducts,
        },
      },
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
    return MealPlannerIntentResult.fromJson(response.data);
  }

  Future<MealPlan> generateMealPlan(Map<String, dynamic> request) async {
    final response = await _dio.post(
      '/meal-planner/generate',
      data: request,
      options: Options(
        headers: {'Content-Type': 'application/json'},
        receiveTimeout: const Duration(seconds: 180),
      ),
    );
    return MealPlan.fromJson(response.data);
  }

  Future<List<MealPlanMeal>> suggestDinner(Map<String, dynamic> request) async {
    final response = await _dio.post(
      '/meal-planner/dinner-suggestion',
      data: request,
      options: Options(
        headers: {'Content-Type': 'application/json'},
        receiveTimeout: const Duration(seconds: 120),
      ),
    );
    final suggestions = response.data['suggestions'] as List? ?? const [];
    return suggestions.map(MealPlanMeal.fromJson).toList();
  }

  Future<MealPlan> getLatestMealPlan() async {
    final response = await _dio.get('/meal-planner/latest');
    return MealPlan.fromJson(response.data);
  }

  Future<MealPlan> getMealPlan(String planId) async {
    final response = await _dio.get('/meal-planner/$planId');
    return MealPlan.fromJson(response.data);
  }

  Future<Map<String, dynamic>> updateMealProgress({
    required String planId,
    required String mealId,
    required Map<String, dynamic> progress,
  }) async {
    final response = await _dio.patch(
      '/meal-planner/$planId/meals/$mealId/progress',
      data: progress,
      options: Options(headers: {'Content-Type': 'application/json'}),
    );
    return Map<String, dynamic>.from(response.data);
  }

  Future<MealPlan> replaceMeal({
    required String planId,
    required String mealId,
  }) async {
    final response = await _dio.post(
      '/meal-planner/$planId/meals/$mealId/replace',
      options: Options(
        headers: {'Content-Type': 'application/json'},
        receiveTimeout: const Duration(seconds: 120),
      ),
    );
    return MealPlan.fromJson(response.data);
  }

  Future<MealPlan> regenerateMeal({
    required String planId,
    required String mealId,
  }) async {
    final response = await _dio.post(
      '/meal-planner/$planId/meals/$mealId/regenerate',
      options: Options(
        headers: {'Content-Type': 'application/json'},
        receiveTimeout: const Duration(seconds: 120),
      ),
    );
    return MealPlan.fromJson(response.data);
  }
} // ← закрывающая скобка класса

// Глобальный инстанс
final apiService = ApiService();
