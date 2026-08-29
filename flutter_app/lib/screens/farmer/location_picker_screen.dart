// CropGuard AI — Farmer: location picker + registration screen.
//
// Farmer flow:
//   1. Interactive map centred on Punjab
//   2. Tap to place/move pin
//   3. Manual lat/lon entry as alternative
//   4. Punjab validation (visual + API)
//   5. Email entry
//   6. Register → navigate to FarmDetailsScreen

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:email_validator/email_validator.dart';
import 'package:cropguard_ai/l10n/generated/app_localizations.dart';

import '../../models/farm_model.dart';
import '../../services/api_service.dart';
import '../../services/cache_service.dart';
import '../../services/connectivity_service.dart';
import '../../utils/constants.dart';
import '../../widgets/offline_banner.dart';
import 'farm_details_screen.dart';

class LocationPickerScreen extends StatefulWidget {
  const LocationPickerScreen({super.key});

  @override
  State<LocationPickerScreen> createState() => _LocationPickerScreenState();
}

class _LocationPickerScreenState extends State<LocationPickerScreen> {
  LatLng? _selectedLocation;
  bool    _outsidePunjab = false;
  bool    _loading       = false;
  bool    _isOnline      = true;
  String? _error;

  final _emailController = TextEditingController();
  final _latController   = TextEditingController();
  final _lonController   = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  final _mapController = MapController();

  final ApiService _api = ApiService();

  @override
  void initState() {
    super.initState();
    _checkConnectivity();
  }

  Future<void> _checkConnectivity() async {
    final online = await ConnectivityService.instance.isOnline();
    setState(() => _isOnline = online);
  }

  bool _isPunjab(double lat, double lon) {
    return lat >= AppConstants.punjabSouth &&
           lat <= AppConstants.punjabNorth &&
           lon >= AppConstants.punjabWest  &&
           lon <= AppConstants.punjabEast;
  }

  void _onMapTap(TapPosition _, LatLng point) {
    setState(() {
      _selectedLocation = point;
      _outsidePunjab = !_isPunjab(point.latitude, point.longitude);
      _latController.text = point.latitude.toStringAsFixed(5);
      _lonController.text = point.longitude.toStringAsFixed(5);
      _error = null;
    });
  }

  void _applyManualCoords() {
    final lat = double.tryParse(_latController.text.trim());
    final lon = double.tryParse(_lonController.text.trim());
    if (lat == null || lon == null) {
      setState(() => _error = 'Invalid coordinates.');
      return;
    }
    setState(() {
      _selectedLocation = LatLng(lat, lon);
      _outsidePunjab = !_isPunjab(lat, lon);
      _error = null;
    });
    _mapController.move(_selectedLocation!, 10);
  }

  Future<void> _register() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedLocation == null) {
      setState(() => _error = 'Please select a location on the map.');
      return;
    }
    if (_outsidePunjab) return;

    setState(() { _loading = true; _error = null; });

    try {
      final farm = await _api.registerFarm(
        latitude:  _selectedLocation!.latitude,
        longitude: _selectedLocation!.longitude,
        email:     _emailController.text.trim(),
      );
      await CacheService.instance.saveFarmDetails(farm);

      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => FarmDetailsScreen(farm: farm)),
      );
    } on ApiException catch (e) {
      setState(() {
        _error = e.statusCode == 422
            ? 'This location is outside Punjab. CropGuard AI currently supports Punjab only.'
            : e.message;
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;

    return Scaffold(
      backgroundColor: const Color(0xFFF1F8E9),
      appBar: AppBar(
        backgroundColor: Colors.green.shade700,
        foregroundColor: Colors.white,
        title: const Text('CropGuard AI'),
        actions: [
          IconButton(
            icon: const Icon(Icons.admin_panel_settings),
            tooltip: 'Admin',
            onPressed: () => Navigator.of(context).pushNamed('/admin'),
          ),
        ],
      ),
      body: Column(
        children: [
          if (!_isOnline) const OfflineBanner(),
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                children: [
                  // ── Map ───────────────────────────────────────────────────
                  Container(
                    height: 320,
                    margin: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 6)],
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: FlutterMap(
                      mapController: _mapController,
                      options: MapOptions(
                        initialCenter: const LatLng(
                          AppConstants.punjabCentreLat,
                          AppConstants.punjabCentreLon,
                        ),
                        initialZoom: 7.5,
                        onTap: _onMapTap,
                      ),
                      children: [
                        TileLayer(
                          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                          userAgentPackageName: 'com.cropguard.ai',
                        ),
                        if (_selectedLocation != null)
                          MarkerLayer(
                            markers: [
                              Marker(
                                point: _selectedLocation!,
                                width: 40,
                                height: 40,
                                child: Icon(
                                  Icons.location_pin,
                                  color: _outsidePunjab ? Colors.red : Colors.green.shade700,
                                  size: 40,
                                ),
                              ),
                            ],
                          ),
                      ],
                    ),
                  ),

                  // ── Map hint ──────────────────────────────────────────────
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Text(
                      l10n.selectFarmLocation,
                      style: const TextStyle(fontSize: 13, color: Colors.black54),
                      textAlign: TextAlign.center,
                    ),
                  ),
                  const SizedBox(height: 4),

                  // ── Outside Punjab warning ────────────────────────────────
                  if (_outsidePunjab)
                    Container(
                      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: Colors.red.shade50,
                        border: Border.all(color: Colors.red),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.warning_amber, color: Colors.red),
                          const SizedBox(width: 8),
                          Expanded(child: Text(l10n.outsidePunjabMessage,
                            style: const TextStyle(color: Colors.red))),
                        ],
                      ),
                    ),

                  // ── Manual coords ─────────────────────────────────────────
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    child: Row(
                      children: [
                        Expanded(
                          child: TextFormField(
                            controller: _latController,
                            decoration: const InputDecoration(
                              labelText: 'Latitude',
                              border: OutlineInputBorder(),
                              isDense: true,
                            ),
                            keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: TextFormField(
                            controller: _lonController,
                            decoration: const InputDecoration(
                              labelText: 'Longitude',
                              border: OutlineInputBorder(),
                              isDense: true,
                            ),
                            keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
                          ),
                        ),
                        const SizedBox(width: 8),
                        ElevatedButton(
                          onPressed: _applyManualCoords,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.green.shade700,
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(vertical: 13),
                          ),
                          child: const Text('Go'),
                        ),
                      ],
                    ),
                  ),

                  // ── Registration form ─────────────────────────────────────
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Form(
                      key: _formKey,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          TextFormField(
                            controller: _emailController,
                            decoration: InputDecoration(
                              labelText: l10n.emailAddress,
                              border: const OutlineInputBorder(),
                              prefixIcon: const Icon(Icons.email_outlined),
                            ),
                            keyboardType: TextInputType.emailAddress,
                            validator: (v) {
                              if (v == null || v.isEmpty) return 'Email is required.';
                              if (!EmailValidator.validate(v.trim())) return 'Enter a valid email.';
                              return null;
                            },
                          ),
                          const SizedBox(height: 16),

                          if (_error != null)
                            Container(
                              padding: const EdgeInsets.all(10),
                              margin: const EdgeInsets.only(bottom: 8),
                              decoration: BoxDecoration(
                                color: Colors.red.shade50,
                                border: Border.all(color: Colors.red.shade300),
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Text(_error!, style: TextStyle(color: Colors.red.shade700)),
                            ),

                          ElevatedButton.icon(
                            onPressed: (_loading || _outsidePunjab || !_isOnline) ? null : _register,
                            icon: _loading
                                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                : const Icon(Icons.agriculture),
                            label: Text(l10n.registerFarm),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.green.shade700,
                              foregroundColor: Colors.white,
                              padding: const EdgeInsets.symmetric(vertical: 14),
                              textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                            ),
                          ),
                          const SizedBox(height: 24),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _emailController.dispose();
    _latController.dispose();
    _lonController.dispose();
    super.dispose();
  }
}
