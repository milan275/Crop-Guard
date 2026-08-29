// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Hindi (`hi`).
class AppLocalizationsHi extends AppLocalizations {
  AppLocalizationsHi([String locale = 'hi']) : super(locale);

  @override
  String get appTitle => 'क्रॉपगार्ड AI';

  @override
  String get selectFarmLocation =>
      'अपने खेत का स्थान चुनने के लिए मानचित्र पर टैप करें।';

  @override
  String get outsidePunjabMessage =>
      'यह स्थान पंजाब के बाहर है। CropGuard AI वर्तमान में केवल पंजाब का समर्थन करता है।';

  @override
  String get emailAddress => 'ईमेल पता';

  @override
  String get registerFarm => 'खेत पंजीकृत करें';

  @override
  String get myFarm => 'मेरा खेत';

  @override
  String get location => 'स्थान';

  @override
  String get district => 'जिला';

  @override
  String get crop => 'फसल';

  @override
  String get cropStage => 'फसल अवस्था';

  @override
  String get riskLevel => 'वर्तमान जोखिम';

  @override
  String get forecast => 'पूर्वानुमान';

  @override
  String get recommendation => 'सिफारिश';

  @override
  String get lastSatelliteUpdate => 'उपग्रह अपडेट';

  @override
  String get lastWeatherUpdate => 'मौसम अपडेट';

  @override
  String get selectDistrict => 'जिला चुनें';

  @override
  String get offlineMessage =>
      'इंटरनेट कनेक्शन नहीं। अंतिम उपलब्ध जानकारी दिखाई जा रही है।';

  @override
  String get lastUpdated => 'अंतिम अपडेट';

  @override
  String get riskMapTitle => 'जोखिम मानचित्र';

  @override
  String get applyOverride => 'ओवरराइड लागू करें';

  @override
  String get overridePrediction => 'पूर्वानुमान (0.0 – 1.0)';

  @override
  String get overrideSuggestion => 'सुझाव / सिफारिश';
}
