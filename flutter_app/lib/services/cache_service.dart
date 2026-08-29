// CropGuard AI — Offline cache service.
//
// Caches farm details, last risk map, and last update timestamp.
// When offline, the app shows cached data with a clear "offline" banner.
// Cached data is NEVER presented as live without explicit timestamp disclosure.

import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../utils/constants.dart';
import '../models/farm_model.dart';

class CacheService {
  static CacheService? _instance;
  SharedPreferences?   _prefs;

  CacheService._();

  static CacheService get instance {
    _instance ??= CacheService._();
    return _instance!;
  }

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  // ── Farm ──────────────────────────────────────────────────────────────────

  Future<void> saveFarmDetails(FarmModel farm) async {
    await _prefs?.setString(AppConstants.kFarmDetails, jsonEncode(farm.toJson()));
    await _prefs?.setInt(AppConstants.kFarmId, farm.farmId ?? 0);
    await _prefs?.setString(AppConstants.kLastUpdated, DateTime.now().toIso8601String());
  }

  FarmModel? loadFarmDetails() {
    final json = _prefs?.getString(AppConstants.kFarmDetails);
    if (json == null) return null;
    try {
      return FarmModel.fromJson(jsonDecode(json) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  int? loadFarmId() => _prefs?.getInt(AppConstants.kFarmId);

  String? loadLastUpdated() => _prefs?.getString(AppConstants.kLastUpdated);

  // ── Risk map ──────────────────────────────────────────────────────────────

  Future<void> saveRiskMapJson(String geojson) async {
    // Store only a summary (first 200 cells) to avoid huge prefs entries.
    // Full map is fetched fresh when online.
    try {
      final decoded = jsonDecode(geojson) as Map<String, dynamic>;
      final features = (decoded['features'] as List).take(200).toList();
      final summary = {'type': 'FeatureCollection', 'features': features};
      await _prefs?.setString(AppConstants.kLastRiskMap, jsonEncode(summary));
    } catch (_) {
      await _prefs?.setString(AppConstants.kLastRiskMap, geojson);
    }
  }

  String? loadRiskMapJson() => _prefs?.getString(AppConstants.kLastRiskMap);

  // ── Admin token ───────────────────────────────────────────────────────────
  // NOTE: This stores the token in SharedPreferences for convenience.
  // In production, use flutter_secure_storage.

  Future<void> saveAdminToken(String token) async {
    await _prefs?.setString(AppConstants.kAdminToken, token);
  }

  String? loadAdminToken() => _prefs?.getString(AppConstants.kAdminToken);

  Future<void> clearAdminToken() async {
    await _prefs?.remove(AppConstants.kAdminToken);
  }

  // ── Clear ─────────────────────────────────────────────────────────────────

  Future<void> clearAll() async {
    await _prefs?.clear();
  }
}
