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
  final int dailyCalories;
  final DietType dietType;
  final List<String> allergens;
  final List<String> favoriteProducts;
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
    this.dailyCalories = 2000,
    this.dietType = DietType.normal,
    this.allergens = const [],
    this.favoriteProducts = const [],
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
    int? dailyCalories,
    DietType? dietType,
    List<String>? allergens,
    List<String>? favoriteProducts,
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
      dailyCalories: dailyCalories ?? this.dailyCalories,
      dietType: dietType ?? this.dietType,
      allergens: allergens ?? this.allergens,
      favoriteProducts: favoriteProducts ?? this.favoriteProducts,
      excludedProducts: excludedProducts ?? this.excludedProducts,
      pushNotifications: pushNotifications ?? this.pushNotifications,
      password: password ?? this.password,
    );
  }
}

class SettingsNotifier extends StateNotifier<UserSettings> {
  SettingsNotifier() : super(const UserSettings());

  void updateEmail(String email) =>
      state = state.copyWith(email: email);

  void updateName(String name) =>
      state = state.copyWith(name: name);

  void updateAge(int age) =>
      state = state.copyWith(age: age);

  void updateGender(Gender gender) =>
      state = state.copyWith(gender: gender);

  void updateHeight(int height) =>
      state = state.copyWith(height: height);

  void updateWeight(double weight) =>
      state = state.copyWith(weight: weight);

  void updateDailyCalories(int calories) =>
      state = state.copyWith(dailyCalories: calories);

  void updateDietType(DietType type) =>
      state = state.copyWith(dietType: type);

  void updateAllergens(List<String> allergens) =>
      state = state.copyWith(allergens: allergens);

  void updateFavoriteProducts(List<String> products) =>
      state = state.copyWith(favoriteProducts: products);

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

final settingsProvider =
    StateNotifierProvider<SettingsNotifier, UserSettings>(
  (ref) => SettingsNotifier(),
);