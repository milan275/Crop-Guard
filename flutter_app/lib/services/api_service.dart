// CropGuard AI — API service (all calls to FastAPI backend).
// Flutter NEVER calls Brevo or any external API directly.

import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../utils/constants.dart';
import '../models/farm_model.dart';
import '../models/risk_cell_model.dart';
import '../models/override_model.dart';

class ApiException implements Exception {
  final int?   statusCode;
  final String message;
  const ApiException(this.message, {this.statusCode});
  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ApiService {
  static const Duration _timeout = Duration(seconds: 20);
  final String baseUrl;

  ApiService({String? baseUrl}) : baseUrl = baseUrl ?? AppConstants.baseUrl;

  Map<String, String> _headers({String? adminToken}) {
    final h = {'Content-Type': 'application/json', 'Accept': 'application/json'};
    if (adminToken != null) h['X-Admin-Token'] = adminToken;
    return h;
  }

  Future<dynamic> _get(String path, {Map<String, String>? query, String? adminToken}) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    try {
      final resp = await http.get(uri, headers: _headers(adminToken: adminToken)).timeout(_timeout);
      return _parse(resp);
    } on SocketException {
      throw const ApiException('No internet connection.', statusCode: 0);
    } on HttpException catch (e) {
      throw ApiException(e.message);
    }
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body, {String? adminToken}) async {
    final uri = Uri.parse('$baseUrl$path');
    try {
      final resp = await http
          .post(uri, headers: _headers(adminToken: adminToken), body: jsonEncode(body))
          .timeout(_timeout);
      return _parse(resp);
    } on SocketException {
      throw const ApiException('No internet connection.', statusCode: 0);
    }
  }

  Future<dynamic> _delete(String path, {String? adminToken}) async {
    final uri = Uri.parse('$baseUrl$path');
    try {
      final resp = await http.delete(uri, headers: _headers(adminToken: adminToken)).timeout(_timeout);
      return _parse(resp);
    } on SocketException {
      throw const ApiException('No internet connection.', statusCode: 0);
    }
  }

  dynamic _parse(http.Response resp) {
    final body = jsonDecode(resp.body);
    if (resp.statusCode >= 200 && resp.statusCode < 300) return body;
    final detail = body is Map ? (body['detail'] ?? body.toString()) : body.toString();
    throw ApiException(detail.toString(), statusCode: resp.statusCode);
  }

  // ── Farms ─────────────────────────────────────────────────────────────────

  Future<FarmModel> registerFarm({
    required double latitude,
    required double longitude,
    required String email,
  }) async {
    final data = await _post('/farms/register', {
      'latitude':  latitude,
      'longitude': longitude,
      'email':     email,
    });
    return FarmModel.fromJson(data as Map<String, dynamic>);
  }

  Future<FarmModel> getFarm(int farmId) async {
    final data = await _get('/farms/$farmId');
    return FarmModel.fromJson(data as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> getFarmRisk(int farmId, {int horizon = 0}) async {
    final data = await _get('/farms/$farmId/risk', query: {'horizon': horizon.toString()});
    return data as Map<String, dynamic>;
  }

  // ── Districts ─────────────────────────────────────────────────────────────

  Future<List<String>> getDistricts() async {
    final data = await _get('/districts');
    final list = (data as Map<String, dynamic>)['districts'] as List<dynamic>;
    return list.cast<String>();
  }

  Future<DistrictRiskMap> getDistrictRiskMap(String district, {int horizon = 0}) async {
    final encoded = Uri.encodeComponent(district);
    final data = await _get('/districts/$encoded/risk-map', query: {'horizon': horizon.toString()});
    return DistrictRiskMap.fromJson(data as Map<String, dynamic>);
  }

  // ── Point risk ────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getPointRisk(double lat, double lon, {int horizon = 0}) async {
    final data = await _get('/risk/point', query: {
      'lat':     lat.toString(),
      'lon':     lon.toString(),
      'horizon': horizon.toString(),
    });
    return data as Map<String, dynamic>;
  }

  // ── Admin overrides ───────────────────────────────────────────────────────

  Future<Map<String, dynamic>> createOverride(
    OverrideModel override,
    String adminToken,
  ) async {
    final data = await _post('/admin/overrides', override.toJson(), adminToken: adminToken);
    return data as Map<String, dynamic>;
  }

  Future<List<OverrideModel>> getOverrides(String adminToken) async {
    final data = await _get('/admin/overrides', adminToken: adminToken);
    final list = (data as Map<String, dynamic>)['overrides'] as List<dynamic>;
    return list.map((e) => OverrideModel.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> deactivateOverride(int overrideId, String adminToken) async {
    await _delete('/admin/overrides/$overrideId', adminToken: adminToken);
  }

  Future<Map<String, dynamic>> triggerAlerts(String adminToken) async {
    final data = await _post('/admin/alerts/trigger', {}, adminToken: adminToken);
    return data as Map<String, dynamic>;
  }

  // ── Health ────────────────────────────────────────────────────────────────

  Future<bool> checkHealth() async {
    try {
      await _get('/health');
      return true;
    } catch (_) {
      return false;
    }
  }
}
