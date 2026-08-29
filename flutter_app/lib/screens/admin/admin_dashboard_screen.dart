// CropGuard AI — Admin dashboard: district heatmap + geographic override.
//
// Admin flow:
//   1. Select district from dropdown
//   2. View district risk heatmap
//   3. Enter geographic rectangle + prediction + suggestion
//   4. Apply override → heatmap updates

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:cropguard_ai/l10n/generated/app_localizations.dart';

import '../../models/override_model.dart';
import '../../models/risk_cell_model.dart';
import '../../services/api_service.dart';
import '../../utils/constants.dart';
import '../../widgets/risk_badge.dart';
import '../../widgets/risk_heatmap_layer.dart';

class AdminDashboardScreen extends StatefulWidget {
  final String adminToken;
  const AdminDashboardScreen({super.key, required this.adminToken});

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  final ApiService _api = ApiService();

  List<String>       _districts        = [];
  String?            _selectedDistrict;
  DistrictRiskMap?   _districtMap;
  List<OverrideModel> _overrides        = [];
  bool               _loadingMap        = false;
  bool               _loadingDistricts  = false;
  bool               _submittingOverride = false;
  String?            _mapError;
  String?            _overrideError;
  String?            _overrideSuccess;
  int                _horizon           = 0;

  // Override form controllers
  final _blLatCtrl  = TextEditingController();
  final _blLonCtrl  = TextEditingController();
  final _trLatCtrl  = TextEditingController();
  final _trLonCtrl  = TextEditingController();
  final _predCtrl   = TextEditingController();
  final _suggCtrl   = TextEditingController();
  final _overrideFormKey = GlobalKey<FormState>();

  @override
  void initState() {
    super.initState();
    _loadDistricts();
    _loadOverrides();
  }

  Future<void> _loadDistricts() async {
    setState(() => _loadingDistricts = true);
    try {
      final districts = await _api.getDistricts();
      setState(() => _districts = districts);
    } on ApiException catch (e) {
      setState(() => _mapError = e.message);
    } finally {
      setState(() => _loadingDistricts = false);
    }
  }

  Future<void> _loadDistrictMap() async {
    if (_selectedDistrict == null) return;
    setState(() { _loadingMap = true; _mapError = null; });
    try {
      final map = await _api.getDistrictRiskMap(_selectedDistrict!, horizon: _horizon);
      setState(() => _districtMap = map);
    } on ApiException catch (e) {
      setState(() => _mapError = e.message);
    } finally {
      setState(() => _loadingMap = false);
    }
  }

  Future<void> _loadOverrides() async {
    try {
      final ovs = await _api.getOverrides(widget.adminToken);
      setState(() => _overrides = ovs);
    } catch (_) {}
  }

  Future<void> _submitOverride() async {
    if (!_overrideFormKey.currentState!.validate()) return;
    setState(() { _submittingOverride = true; _overrideError = null; _overrideSuccess = null; });

    try {
      final override = OverrideModel(
        bottomLeftLat:      double.parse(_blLatCtrl.text.trim()),
        bottomLeftLon:      double.parse(_blLonCtrl.text.trim()),
        topRightLat:        double.parse(_trLatCtrl.text.trim()),
        topRightLon:        double.parse(_trLonCtrl.text.trim()),
        overridePrediction: double.parse(_predCtrl.text.trim()),
        overrideSuggestion: _suggCtrl.text.trim().isEmpty ? null : _suggCtrl.text.trim(),
      );
      final result = await _api.createOverride(override, widget.adminToken);
      setState(() {
        _overrideSuccess =
            'Override applied: ${result['affected_cells']} cells updated. '
            '${result['farms_notified']} farm(s) notified.';
      });
      _loadOverrides();
      if (_selectedDistrict != null) _loadDistrictMap();
    } on ApiException catch (e) {
      setState(() => _overrideError = e.message);
    } finally {
      setState(() => _submittingOverride = false);
    }
  }

  Widget _buildDistrictDropdown(AppLocalizations l10n) {
    return _loadingDistricts
        ? const CircularProgressIndicator()
        : DropdownButtonFormField<String>(
            value: _selectedDistrict,
            isExpanded: true,
            decoration: InputDecoration(
              labelText: l10n.selectDistrict,
              border: const OutlineInputBorder(),
            ),
            items: _districts
                .map((d) => DropdownMenuItem(value: d, child: Text(d)))
                .toList(),
            onChanged: (v) {
              setState(() => _selectedDistrict = v);
              _loadDistrictMap();
            },
          );
  }

  Widget _buildHeatmap() {
    if (_loadingMap) {
      return const SizedBox(height: 300, child: Center(child: CircularProgressIndicator()));
    }
    if (_mapError != null) {
      return Container(
        height: 300,
        alignment: Alignment.center,
        child: Text(_mapError!, style: TextStyle(color: Colors.red.shade700)),
      );
    }
    if (_districtMap == null) {
      return const SizedBox(height: 300,
          child: Center(child: Text('Select a district to view the risk heatmap.')));
    }

    // Compute bounding box of district cells for map centering
    final cells = _districtMap!.cells;
    double clat = AppConstants.punjabCentreLat;
    double clon = AppConstants.punjabCentreLon;
    if (cells.isNotEmpty) {
      clat = cells.map((c) => c.lat).reduce((a, b) => a + b) / cells.length;
      clon = cells.map((c) => c.lon).reduce((a, b) => a + b) / cells.length;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(child: Text(_selectedDistrict ?? '',
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
            if (_districtMap != null) ...[
              RiskBadge(
                riskLevel: _districtMap!.maxRisk >= 0.75 ? 'CRITICAL'
                    : _districtMap!.maxRisk >= 0.55 ? 'HIGH'
                    : _districtMap!.maxRisk >= 0.30 ? 'MODERATE' : 'LOW',
                probability: _districtMap!.meanRisk,
              ),
            ],
          ],
        ),
        const SizedBox(height: 8),
        Card(
          elevation: 3,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          clipBehavior: Clip.antiAlias,
          child: SizedBox(
            height: 320,
            child: Stack(
              children: [
                FlutterMap(
                  options: MapOptions(
                    initialCenter: LatLng(clat, clon),
                    initialZoom: 9.5,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.cropguard.ai',
                    ),
                    if (cells.isNotEmpty)
                      RiskHeatmapLayer(cells: cells),
                  ],
                ),
                const Positioned(bottom: 8, right: 8, child: RiskLegend()),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildOverrideForm(AppLocalizations l10n) {
    Widget coord(TextEditingController ctrl, String label) {
      return TextFormField(
        controller: ctrl,
        decoration: InputDecoration(labelText: label, border: const OutlineInputBorder(), isDense: true),
        keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
        validator: (v) {
          if (v == null || v.isEmpty) return 'Required';
          if (double.tryParse(v.trim()) == null) return 'Invalid number';
          return null;
        },
      );
    }

    return Card(
      elevation: 3,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: _overrideFormKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Override Prediction',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: coord(_blLatCtrl, 'Bottom-left Latitude')),
                const SizedBox(width: 8),
                Expanded(child: coord(_blLonCtrl, 'Bottom-left Longitude')),
              ]),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(child: coord(_trLatCtrl, 'Top-right Latitude')),
                const SizedBox(width: 8),
                Expanded(child: coord(_trLonCtrl, 'Top-right Longitude')),
              ]),
              const SizedBox(height: 8),
              TextFormField(
                controller: _predCtrl,
                decoration: const InputDecoration(
                  labelText: 'Prediction (0.0 – 1.0)',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                validator: (v) {
                  if (v == null || v.isEmpty) return 'Required';
                  final d = double.tryParse(v.trim());
                  if (d == null || d < 0 || d > 1) return 'Must be between 0 and 1';
                  return null;
                },
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _suggCtrl,
                decoration: const InputDecoration(
                  labelText: 'Suggestion / Recommendation',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
                maxLines: 2,
              ),
              const SizedBox(height: 12),
              if (_overrideError != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(_overrideError!,
                      style: TextStyle(color: Colors.red.shade700, fontSize: 13)),
                ),
              if (_overrideSuccess != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(_overrideSuccess!,
                      style: TextStyle(color: Colors.green.shade700, fontSize: 13)),
                ),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: _submittingOverride ? null : _submitOverride,
                  icon: _submittingOverride
                      ? const SizedBox(width: 18, height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.check_circle_outline),
                  label: const Text('Apply Override'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.orange.shade800,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 13),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildOverrideList() {
    final active = _overrides.where((o) => o.active).toList();
    if (active.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Active Overrides',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        ...active.map((o) => Card(
              margin: const EdgeInsets.only(bottom: 8),
              child: ListTile(
                leading: Icon(Icons.edit_location, color: Colors.orange.shade700),
                title: Text('Risk: ${(o.overridePrediction * 100).toStringAsFixed(0)}%'),
                subtitle: Text(
                  'BL: ${o.bottomLeftLat.toStringAsFixed(3)}, ${o.bottomLeftLon.toStringAsFixed(3)} '
                  '→ TR: ${o.topRightLat.toStringAsFixed(3)}, ${o.topRightLon.toStringAsFixed(3)}\n'
                  '${o.overrideSuggestion ?? ''}',
                ),
                trailing: IconButton(
                  icon: const Icon(Icons.delete_outline, color: Colors.red),
                  onPressed: () async {
                    await _api.deactivateOverride(o.id!, widget.adminToken);
                    _loadOverrides();
                    if (_selectedDistrict != null) _loadDistrictMap();
                  },
                ),
              ),
            )),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;

    return Scaffold(
      backgroundColor: const Color(0xFFE8F5E9),
      appBar: AppBar(
        backgroundColor: Colors.green.shade800,
        foregroundColor: Colors.white,
        title: const Text('Admin Dashboard'),
        actions: [
          IconButton(
            icon: const Icon(Icons.notifications_active),
            tooltip: 'Trigger Alerts',
            onPressed: () async {
              final result = await _api.triggerAlerts(widget.adminToken);
              if (!mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('${result['alerts_sent']} alert(s) sent.')),
              );
            },
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── District selector ─────────────────────────────────────────
            _buildDistrictDropdown(l10n),
            const SizedBox(height: 8),

            // ── Horizon chips ─────────────────────────────────────────────
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [0, 1, 3, 7].asMap().entries.map((entry) {
                  final h = entry.value;
                  final labels = ['Current', '+1d', '+3d', '+7d'];
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(labels[entry.key]),
                      selected: h == _horizon,
                      selectedColor: Colors.green.shade700,
                      labelStyle: TextStyle(color: h == _horizon ? Colors.white : Colors.black87),
                      onSelected: (_) {
                        setState(() => _horizon = h);
                        _loadDistrictMap();
                      },
                    ),
                  );
                }).toList(),
              ),
            ),
            const SizedBox(height: 12),

            // ── District heatmap ──────────────────────────────────────────
            _buildHeatmap(),
            const SizedBox(height: 16),

            // ── Override form ─────────────────────────────────────────────
            _buildOverrideForm(l10n),
            const SizedBox(height: 16),

            // ── Active overrides list ─────────────────────────────────────
            _buildOverrideList(),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _blLatCtrl.dispose(); _blLonCtrl.dispose();
    _trLatCtrl.dispose(); _trLonCtrl.dispose();
    _predCtrl.dispose();  _suggCtrl.dispose();
    super.dispose();
  }
}
