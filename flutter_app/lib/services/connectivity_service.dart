// CropGuard AI — Connectivity / offline detection.
// connectivity_plus v6+ returns List<ConnectivityResult> not a single value.

import 'package:connectivity_plus/connectivity_plus.dart';

class ConnectivityService {
  static final ConnectivityService instance = ConnectivityService._();
  ConnectivityService._();

  final Connectivity _connectivity = Connectivity();

  Future<bool> isOnline() async {
    final results = await _connectivity.checkConnectivity();
    return results.isNotEmpty &&
        results.any((r) => r != ConnectivityResult.none);
  }

  Stream<bool> get onlineStream => _connectivity.onConnectivityChanged
      .map((results) =>
          results.isNotEmpty &&
          results.any((r) => r != ConnectivityResult.none));
}
