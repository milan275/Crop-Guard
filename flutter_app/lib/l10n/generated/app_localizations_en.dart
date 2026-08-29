// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'CropGuard AI';

  @override
  String get selectFarmLocation =>
      'Tap the map to select your farm location, or enter coordinates below.';

  @override
  String get outsidePunjabMessage =>
      'This location is outside Punjab. CropGuard AI currently supports Punjab only.';

  @override
  String get emailAddress => 'Email Address';

  @override
  String get registerFarm => 'Register Farm';

  @override
  String get myFarm => 'My Farm';

  @override
  String get location => 'Location';

  @override
  String get district => 'District';

  @override
  String get crop => 'Crop';

  @override
  String get cropStage => 'Crop Stage';

  @override
  String get riskLevel => 'Current Risk';

  @override
  String get forecast => 'Forecast';

  @override
  String get recommendation => 'Recommendation';

  @override
  String get lastSatelliteUpdate => 'Satellite Update';

  @override
  String get lastWeatherUpdate => 'Weather Update';

  @override
  String get selectDistrict => 'Select District';

  @override
  String get offlineMessage =>
      'No internet connection. Showing last available information.';

  @override
  String get lastUpdated => 'Last updated';

  @override
  String get riskMapTitle => 'Risk Map';

  @override
  String get applyOverride => 'Apply Override';

  @override
  String get overridePrediction => 'Prediction (0.0 – 1.0)';

  @override
  String get overrideSuggestion => 'Suggestion / Recommendation';
}
