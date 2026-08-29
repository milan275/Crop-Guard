// CropGuard AI — Flutter app entry point.

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:cropguard_ai/l10n/generated/app_localizations.dart';

import 'services/cache_service.dart';
import 'screens/farmer/location_picker_screen.dart';
import 'screens/farmer/farm_details_screen.dart';
import 'screens/admin/admin_login_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await CacheService.instance.init();
  runApp(const CropGuardApp());
}

class CropGuardApp extends StatelessWidget {
  const CropGuardApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'CropGuard AI',
      debugShowCheckedModeBanner: false,

      // ── Localisation ──────────────────────────────────────────────────────
      localizationsDelegates: [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [
        Locale('en'),   // English (default)
        Locale('pa'),   // Punjabi
        Locale('hi'),   // Hindi
      ],

      // ── Theme ─────────────────────────────────────────────────────────────
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.green,
          brightness: Brightness.light,
        ),
        appBarTheme: const AppBarTheme(centerTitle: false, elevation: 0),
        cardTheme: CardThemeData(
          elevation: 2,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
        inputDecorationTheme: const InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
        ),
      ),

      // ── Home ──────────────────────────────────────────────────────────────
      home: const _RootRouter(),
      routes: {
        '/admin': (ctx) => const AdminLoginScreen(),
      },
    );
  }
}

/// Routes to FarmDetailsScreen if a cached farm exists, otherwise to
/// LocationPickerScreen for first-time registration.
class _RootRouter extends StatelessWidget {
  const _RootRouter();

  @override
  Widget build(BuildContext context) {
    final cachedFarm = CacheService.instance.loadFarmDetails();
    if (cachedFarm != null && (cachedFarm.farmId ?? 0) > 0) {
      return FarmDetailsScreen(farm: cachedFarm);
    }
    return const LocationPickerScreen();
  }
}
