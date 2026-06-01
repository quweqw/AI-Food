import 'package:flutter_riverpod/flutter_riverpod.dart';

enum Gender { male, female }

enum DietType { bulk, cut, normal }

class UserSettings {
  final String email;
  final String name;
  final int age;
  final Gender gender;
  final int height;
  final double weight;
  final String activityLevel;
  final int dailyCalories;
  final DietType dietType;
  final int mealsPerDay;
  final List<String> allergens;
  final List<String> favoriteProducts;
  final List<String> dislikedProducts;
  final List<String> excludedProducts;
  final bool pushNotifications;
  final String password;

  const UserSettings({
    this.email = 'user@gmail.com',
    this.name = 'Иванов Иван',
    this.age = 25,
    this.gender = Gender.male,
    this.height = 175,
    this.weight = 70,
    this.activityLevel = 'moderate',
    this.dailyCalories = 2000,
    this.dietType = DietType.normal,
    this.mealsPerDay = 3,
    this.allergens = const [],
    this.favoriteProducts = const [],
    this.dislikedProducts = const [],
    this.excludedProducts = const [],
    this.pushNotifications = true,
    this.password = '',
  });

  UserSettings copyWith({
    String? email,
    String? name,
    int? age,
    Gender? gender,
    int? height,
    double? weight,
    String? activityLevel,
    int? dailyCalories,
    DietType? dietType,
    int? mealsPerDay,
    List<String>? allergens,
    List<String>? favoriteProducts,
    List<String>? dislikedProducts,
    List<String>? excludedProducts,
    bool? pushNotifications,
    String? password,
  }) {
    return UserSettings(
      email: email ?? this.email,
      name: name ?? this.name,
      age: age ?? this.age,
      gender: gender ?? this.gender,
      height: height ?? this.height,
      weight: weight ?? this.weight,
      activityLevel: activityLevel ?? this.activityLevel,
      dailyCalories: dailyCalories ?? this.dailyCalories,
      dietType: dietType ?? this.dietType,
      mealsPerDay: mealsPerDay ?? this.mealsPerDay,
      allergens: allergens ?? this.allergens,
      favoriteProducts: favoriteProducts ?? this.favoriteProducts,
      dislikedProducts: dislikedProducts ?? this.dislikedProducts,
      excludedProducts: excludedProducts ?? this.excludedProducts,
      pushNotifications: pushNotifications ?? this.pushNotifications,
      password: password ?? this.password,
    );
  }
}

class SettingsNotifier extends StateNotifier<UserSettings> {
  SettingsNotifier() : super(const UserSettings());

  Future<void> loadFromBackend(Map<String, dynamic> data) async {
    final genderMap = {'male': Gender.male, 'female': Gender.female};
    final dietMap = {
      'bulk': DietType.bulk,
      'cut': DietType.cut,
      'normal': DietType.normal,
      'muscle_gain': DietType.bulk,
      'weight_loss': DietType.cut,
      'balanced': DietType.normal,
    };
    final heightValue = data['height_cm'] ?? data['height'] ?? 175;
    final weightValue = data['weight_kg'] ?? data['weight'] ?? 70.0;
    final caloriesValue =
        data['target_calories'] ?? data['daily_calories'] ?? 2000;

    state = state.copyWith(
      email: data['email'],
      name: data['name'] ?? state.name,
      age: data['age'] ?? 25,
      gender: genderMap[data['sex'] ?? data['gender']] ?? Gender.male,
      height: heightValue is num ? heightValue.toInt() : 175,
      weight: weightValue is num ? weightValue.toDouble() : 70.0,
      activityLevel: data['activity_level'] ?? 'moderate',
      dailyCalories: caloriesValue is num ? caloriesValue.toInt() : 2000,
      dietType: dietMap[data['goal'] ?? data['diet_type']] ?? DietType.normal,
      mealsPerDay: data['meals_per_day'] ?? 3,
      allergens: List<String>.from(data['allergies'] ?? data['allergens'] ?? []),
      favoriteProducts: List<String>.from(data['preferred_ingredients'] ??
          data['favorite_products'] ??
          []),
      dislikedProducts: List<String>.from(data['disliked_ingredients'] ??
          data['disliked_products'] ??
          []),
      excludedProducts: List<String>.from(data['excluded_ingredients'] ??
          data['excluded_products'] ??
          []),
      pushNotifications: data['push_notifications'] ?? true,
    );
  }

  void updateName(String name) => state = state.copyWith(name: name);

  void updateAge(int age) => state = state.copyWith(age: age);

  void updateGender(Gender gender) => state = state.copyWith(gender: gender);

  void updateHeight(int height) => state = state.copyWith(height: height);

  void updateWeight(double weight) => state = state.copyWith(weight: weight);

  void updateActivityLevel(String value) =>
      state = state.copyWith(activityLevel: value);

  void updateDailyCalories(int calories) =>
      state = state.copyWith(dailyCalories: calories);

  void updateDietType(DietType type) => state = state.copyWith(dietType: type);

  void updateMealsPerDay(int value) =>
      state = state.copyWith(mealsPerDay: value);

  void updateAllergens(List<String> allergens) =>
      state = state.copyWith(allergens: allergens);

  void updateFavoriteProducts(List<String> products) =>
      state = state.copyWith(favoriteProducts: products);

  void updateDislikedProducts(List<String> products) =>
      state = state.copyWith(dislikedProducts: products);

  void updateExcludedProducts(List<String> products) =>
      state = state.copyWith(excludedProducts: products);

  void updatePushNotifications(bool value) =>
      state = state.copyWith(pushNotifications: value);

  void updatePassword(String password) =>
      state = state.copyWith(password: password);

  // Вызывается после регистрации
  void initFromRegistration(String email) =>
      state = state.copyWith(email: email);
}

final settingsProvider = StateNotifierProvider<SettingsNotifier, UserSettings>(
  (ref) => SettingsNotifier(),
);
