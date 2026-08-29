// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Panjabi Punjabi (`pa`).
class AppLocalizationsPa extends AppLocalizations {
  AppLocalizationsPa([String locale = 'pa']) : super(locale);

  @override
  String get appTitle => 'ਕ੍ਰੌਪਗਾਰਡ AI';

  @override
  String get selectFarmLocation =>
      'ਆਪਣੀ ਖੇਤੀਬਾੜੀ ਦੀ ਜਗ੍ਹਾ ਚੁਣਨ ਲਈ ਨਕਸ਼ੇ \'ਤੇ ਟੈਪ ਕਰੋ।';

  @override
  String get outsidePunjabMessage =>
      'ਇਹ ਸਥਾਨ ਪੰਜਾਬ ਤੋਂ ਬਾਹਰ ਹੈ। CropGuard AI ਫ਼ਿਲਹਾਲ ਸਿਰਫ਼ ਪੰਜਾਬ ਲਈ ਸਹਾਇਕ ਹੈ।';

  @override
  String get emailAddress => 'ਈਮੇਲ ਪਤਾ';

  @override
  String get registerFarm => 'ਖੇਤ ਰਜਿਸਟਰ ਕਰੋ';

  @override
  String get myFarm => 'ਮੇਰਾ ਖੇਤ';

  @override
  String get location => 'ਸਥਾਨ';

  @override
  String get district => 'ਜ਼ਿਲ੍ਹਾ';

  @override
  String get crop => 'ਫ਼ਸਲ';

  @override
  String get cropStage => 'ਫ਼ਸਲ ਦੀ ਅਵਸਥਾ';

  @override
  String get riskLevel => 'ਮੌਜੂਦਾ ਜੋਖ਼ਮ';

  @override
  String get forecast => 'ਅਨੁਮਾਨ';

  @override
  String get recommendation => 'ਸਿਫ਼ਾਰਸ਼';

  @override
  String get lastSatelliteUpdate => 'ਉਪਗ੍ਰਹਿ ਅਪਡੇਟ';

  @override
  String get lastWeatherUpdate => 'ਮੌਸਮ ਅਪਡੇਟ';

  @override
  String get selectDistrict => 'ਜ਼ਿਲ੍ਹਾ ਚੁਣੋ';

  @override
  String get offlineMessage =>
      'ਇੰਟਰਨੈੱਟ ਕੁਨੈਕਸ਼ਨ ਨਹੀਂ। ਆਖਰੀ ਉਪਲਬਧ ਜਾਣਕਾਰੀ ਦਿਖਾਈ ਜਾ ਰਹੀ ਹੈ।';

  @override
  String get lastUpdated => 'ਆਖਰੀ ਅਪਡੇਟ';

  @override
  String get riskMapTitle => 'ਜੋਖ਼ਮ ਨਕਸ਼ਾ';

  @override
  String get applyOverride => 'ਓਵਰਰਾਈਡ ਲਾਗੂ ਕਰੋ';

  @override
  String get overridePrediction => 'ਅਨੁਮਾਨ (0.0 – 1.0)';

  @override
  String get overrideSuggestion => 'ਸੁਝਾਅ / ਸਿਫ਼ਾਰਸ਼';
}
