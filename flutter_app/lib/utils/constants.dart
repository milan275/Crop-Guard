// CropGuard AI — app-wide constants.

class AppConstants {
  // Backend URL — change to your server address when deploying.
  // Use 10.0.2.2 for Android emulator pointing to localhost.
  static const String baseUrl = 'http://10.0.2.2:8000';

  // Punjab bounding box
  static const double punjabWest  = 73.8;
  static const double punjabSouth = 29.5;
  static const double punjabEast  = 76.9;
  static const double punjabNorth = 32.6;

  // Map centre (approximate centre of Punjab)
  static const double punjabCentreLat = 31.1;
  static const double punjabCentreLon = 75.35;

  // Risk colours
  static const Map<String, int> riskColours = {
    'LOW':      0xFF4CAF50, // green
    'MODERATE': 0xFFFFEB3B, // yellow
    'HIGH':     0xFFFF9800, // orange
    'CRITICAL': 0xFFF44336, // red
  };

  // Offline cache keys
  static const String kFarmDetails    = 'farm_details';
  static const String kFarmId         = 'farm_id';
  static const String kLastRiskMap    = 'last_risk_map';
  static const String kLastUpdated    = 'last_updated';
  static const String kAdminToken     = 'admin_token';
}
