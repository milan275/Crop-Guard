// CropGuard AI — Farmer: farm details and risk map screen.

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:cropguard_ai/l10n/generated/app_localizations.dart';

import '../../models/farm_model.dart';
import '../../models/risk_cell_model.dart';
import '../../services/api_service.dart';
import '../../services/cache_service.dart';
import '../../services/connectivity_service.dart';
import '../../widgets/info_row.dart';
import '../../widgets/offline_banner.dart';
import '../../widgets/risk_badge.dart';
import '../../widgets/risk_heatmap_layer.dart';
import '../../utils/constants.dart';

class FarmDetailsScreen extends StatefulWidget {
  final FarmModel farm;
  const FarmDetailsScreen({super.key, required this.farm});

  @override
  State<FarmDetailsScreen> createState() => _FarmDetailsScreenState();
}

class _FarmDetailsScreenState extends State<FarmDetailsScreen> {
  late FarmModel    _farm;
  List<RiskCellModel> _cells = [];
  bool   _loading   = false;
  bool   _isOnline  = true;
  String? _error;
  int    _horizon   = 0;

  final ApiService _api = ApiService();

  @override
  void initState() {
    super.initState();
    _farm = widget.farm;
    _refresh();
  }

  Future<void> _refresh() async {
    final online = await ConnectivityService.instance.isOnline();
    setState(() { _isOnline = online; _loading = true; _error = null; });

    if (!online) {
      // Load from cache
      final cached = CacheService.instance.loadFarmDetails();
      setState(() { if (cached != null) _farm = cached; _loading = false; });
      return;
    }

    try {
      final farmId = _farm.farmId;
      if (farmId != null) {
        final risk = await _api.getFarmRisk(farmId, horizon: _horizon);
        final updated = FarmModel.fromJson(risk);
        await CacheService.instance.saveFarmDetails(updated);

        // Load district risk for map overlay
        if (updated.district != null) {
          final districtMap = await _api.getDistrictRiskMap(updated.district!, horizon: _horizon);
          setState(() { _cells = districtMap.cells; });
        }

        setState(() { _farm = updated; });
      }
    } on ApiException catch (e) {
      setState(() { _error = e.message; });
    } finally {
      setState(() { _loading = false; });
    }
  }

  Widget _buildForecastChips() {
    const horizons = [0, 1, 3, 7];
    const labels   = ['Now', '+1d', '+3d', '+7d'];
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: List.generate(horizons.length, (i) {
          final selected = horizons[i] == _horizon;
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              label: Text(labels[i]),
              selected: selected,
              selectedColor: Colors.green.shade700,
              labelStyle: TextStyle(color: selected ? Colors.white : Colors.black87),
              onSelected: (_) {
                setState(() => _horizon = horizons[i]);
                _refresh();
              },
            ),
          );
        }),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    final lat  = _farm.latitude;
    final lon  = _farm.longitude;

    return Scaffold(
      backgroundColor: const Color(0xFFF1F8E9),
      appBar: AppBar(
        backgroundColor: Colors.green.shade700,
        foregroundColor: Colors.white,
        title: Text(l10n.myFarm),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _refresh,
          ),
        ],
      ),
      body: Column(
        children: [
          if (!_isOnline) OfflineBanner(lastUpdated: CacheService.instance.loadLastUpdated()),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: _refresh,
                    child: SingleChildScrollView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          // ── Risk card ─────────────────────────────────────
                          Card(
                            elevation: 3,
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                            child: Padding(
                              padding: const EdgeInsets.all(16),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                    children: [
                                      Text(l10n.myFarm,
                                          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                                      RiskBadge(
                                        riskLevel:   _farm.riskLevel,
                                        probability: _farm.riskProbability,
                                      ),
                                    ],
                                  ),
                                  const Divider(height: 20),
                                  InfoRow(label: l10n.location,
                                      value: '${lat.toStringAsFixed(4)}° N, ${lon.toStringAsFixed(4)}° E',
                                      icon: Icons.location_on),
                                  InfoRow(label: l10n.district,   value: _farm.district,    icon: Icons.map),
                                  InfoRow(label: l10n.crop,       value: _farm.crop?.toUpperCase(), icon: Icons.grass),
                                  InfoRow(label: l10n.cropStage,  value: _farm.cropStage,   icon: Icons.eco),
                                  InfoRow(label: l10n.riskLevel,
                                      valueWidget: RiskBadge(
                                          riskLevel: _farm.riskLevel,
                                          probability: _farm.riskProbability,
                                          fontSize: 12),
                                      icon: Icons.warning_amber),
                                  InfoRow(label: l10n.forecast,
                                      value: _farm.forecastHorizon ?? '—',
                                      icon: Icons.calendar_today),
                                  if (_farm.recommendation != null)
                                    InfoRow(label: l10n.recommendation,
                                        value: _farm.recommendation,
                                        icon: Icons.tips_and_updates),
                                  InfoRow(label: l10n.lastSatelliteUpdate,
                                      value: _farm.satelliteTimestamp ?? '—',
                                      icon: Icons.satellite_alt),
                                  InfoRow(label: l10n.lastWeatherUpdate,
                                      value: _farm.weatherTimestamp ?? '—',
                                      icon: Icons.cloud),
                                  if (_farm.dataNote != null)
                                    Padding(
                                      padding: const EdgeInsets.only(top: 8),
                                      child: Text(
                                        '* ${_farm.dataNote}',
                                        style: const TextStyle(fontSize: 11, color: Colors.black45, fontStyle: FontStyle.italic),
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ),

                          const SizedBox(height: 12),
                          // ── Forecast selector ─────────────────────────────
                          _buildForecastChips(),
                          const SizedBox(height: 12),

                          if (_error != null)
                            Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: Text(_error!,
                                  style: TextStyle(color: Colors.red.shade700, fontSize: 13)),
                            ),

                          // ── Risk map ──────────────────────────────────────
                          Card(
                            elevation: 3,
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                            clipBehavior: Clip.antiAlias,
                            child: SizedBox(
                              height: 300,
                              child: Stack(
                                children: [
                                  FlutterMap(
                                    options: MapOptions(
                                      initialCenter: LatLng(lat, lon),
                                      initialZoom: 10,
                                    ),
                                    children: [
                                      TileLayer(
                                        urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                                        userAgentPackageName: 'com.cropguard.ai',
                                      ),
                                      if (_cells.isNotEmpty)
                                        RiskHeatmapLayer(cells: _cells),
                                      MarkerLayer(
                                        markers: [
                                          Marker(
                                            point: LatLng(lat, lon),
                                            width: 36,
                                            height: 36,
                                            child: const Icon(Icons.location_pin,
                                                color: Colors.blue, size: 36),
                                          ),
                                        ],
                                      ),
                                    ],
                                  ),
                                  const Positioned(
                                    bottom: 8, right: 8,
                                    child: RiskLegend(),
                                  ),
                                ],
                              ),
                            ),
                          ),
                          const SizedBox(height: 24),
                        ],
                      ),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}
