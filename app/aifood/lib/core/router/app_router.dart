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

final appRouter = GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(path: '/',         builder: (_, __) => const WelcomeScreen()),
    GoRoute(path: '/register', builder: (_, __) => const RegisterScreen()),
    GoRoute(path: '/login',    builder: (_, __) => const LoginScreen()),
    GoRoute(
      path: '/chat',
      builder: (_, state) => ChatScreen(
        chatId: state.uri.queryParameters['id'],
      ),
    ),
    GoRoute(path: '/history',  builder: (_, __) => const HistoryScreen()),
    GoRoute(path: '/settings', builder: (_, __) => const SettingsScreen()),
    GoRoute(path: '/profile',  builder: (_, __) => const ProfileScreen()),
    GoRoute(path: '/about',    builder: (_, __) => const AboutScreen()),
    GoRoute(path: '/contact',  builder: (_, __) => const ContactScreen()),
  ],
);