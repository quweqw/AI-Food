import 'package:go_router/go_router.dart';
import '../../features/auth/screens/welcome_screen.dart';
import '../../features/auth/screens/register_screen.dart';
import '../../features/auth/screens/login_screen.dart';
import '../../features/chat/screens/chat_screen.dart';
import '../../features/chat/screens/history_screen.dart';
import '../../features/settings/screens/settings_screen.dart';
import '../../features/settings/screens/profile_screen.dart';
import '../../features/about/screens/about_screen.dart';
import '../../features/about/screens/contact_screen.dart';
import '../../features/meal_planner/screens/meal_planner_screen.dart';
import '../../features/meal_planner/screens/recipe_detail_screen.dart';
import '../../features/meal_planner/models/meal_plan_models.dart';
import '../../core/services/api_service.dart';

final appRouter = GoRouter(
  initialLocation: '/',
  redirect: (context, state) async {
    final loggedIn = await apiService.isLoggedIn();
    final pendingVerificationEmail =
        await apiService.getPendingVerificationEmail();
    final isAuthRoute = state.matchedLocation == '/' ||
        state.matchedLocation == '/login' ||
        state.matchedLocation == '/register';
    final isPendingVerificationRoute =
        state.matchedLocation == '/register' &&
            state.uri.queryParameters['verify'] == '1';

    if (!loggedIn &&
        pendingVerificationEmail != null &&
        state.matchedLocation == '/') {
      return '/register?verify=1&email=${Uri.encodeComponent(pendingVerificationEmail)}';
    }
    if (!loggedIn &&
        pendingVerificationEmail != null &&
        !isPendingVerificationRoute &&
        state.matchedLocation != '/login') {
      return '/register?verify=1&email=${Uri.encodeComponent(pendingVerificationEmail)}';
    }
    if (!loggedIn && !isAuthRoute) return '/login';
    if (loggedIn && isAuthRoute) return '/chat';
    return null;
  },
  routes: [
    GoRoute(path: '/', builder: (_, __) => const WelcomeScreen()),
    GoRoute(
      path: '/register',
      builder: (_, state) => RegisterScreen(
        initialEmail: state.uri.queryParameters['email'],
        verifyOnly: state.uri.queryParameters['verify'] == '1',
      ),
    ),
    GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
    GoRoute(
      path: '/chat',
      builder: (_, state) => ChatScreen(
        chatId: state.uri.queryParameters['id'],
      ),
    ),
    GoRoute(path: '/history', builder: (_, __) => const HistoryScreen()),
    GoRoute(
      path: '/settings',
      builder: (_, state) => SettingsScreen(
        openChatOnSave: state.uri.queryParameters['onboarding'] == '1',
      ),
    ),
    GoRoute(path: '/profile', builder: (_, __) => const ProfileScreen()),
    GoRoute(path: '/about', builder: (_, __) => const AboutScreen()),
    GoRoute(path: '/contact', builder: (_, __) => const ContactScreen()),
    GoRoute(
      path: '/meal-planner',
      builder: (_, __) => const MealPlannerScreen(),
    ),
    GoRoute(
      path: '/meal-planner/recipe/:mealId',
      builder: (_, state) => RecipeDetailScreen(
        mealId: state.pathParameters['mealId'] ?? '',
        initialMeal: state.extra is MealPlanMeal
            ? state.extra as MealPlanMeal
            : null,
      ),
    ),
  ],
);
