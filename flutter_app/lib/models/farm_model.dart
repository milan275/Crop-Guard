// CropGuard AI — Farm data model.

class FarmModel {
  final int?    farmId;
  final double  latitude;
  final double  longitude;
  final String? district;
  final String? crop;
  final String? cropStage;
  final String? riskLevel;
  final double? riskProbability;
  final String? forecastHorizon;
  final String? recommendation;
  final String? satelliteTimestamp;
  final String? weatherTimestamp;
  final String? lastUpdated;
  final String? dataNote;

  const FarmModel({
    this.farmId,
    required this.latitude,
    required this.longitude,
    this.district,
    this.crop,
    this.cropStage,
    this.riskLevel,
    this.riskProbability,
    this.forecastHorizon,
    this.recommendation,
    this.satelliteTimestamp,
    this.weatherTimestamp,
    this.lastUpdated,
    this.dataNote,
  });

  factory FarmModel.fromJson(Map<String, dynamic> json) {
    return FarmModel(
      farmId:             json['farm_id'] as int?,
      latitude:           (json['latitude'] as num).toDouble(),
      longitude:          (json['longitude'] as num).toDouble(),
      district:           json['district'] as String?,
      crop:               json['crop'] as String?,
      cropStage:          json['crop_stage'] as String?,
      riskLevel:          json['risk_level'] as String?,
      riskProbability:    json['risk_probability'] != null
                            ? (json['risk_probability'] as num).toDouble()
                            : null,
      forecastHorizon:    json['forecast_horizon'] as String?,
      recommendation:     json['recommendation'] as String?,
      satelliteTimestamp: json['satellite_timestamp'] as String?,
      weatherTimestamp:   json['weather_timestamp'] as String?,
      lastUpdated:        json['last_updated'] as String?,
      dataNote:           json['data_note'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
    'farm_id':              farmId,
    'latitude':             latitude,
    'longitude':            longitude,
    'district':             district,
    'crop':                 crop,
    'crop_stage':           cropStage,
    'risk_level':           riskLevel,
    'risk_probability':     riskProbability,
    'forecast_horizon':     forecastHorizon,
    'recommendation':       recommendation,
    'satellite_timestamp':  satelliteTimestamp,
    'weather_timestamp':    weatherTimestamp,
    'last_updated':         lastUpdated,
    'data_note':            dataNote,
  };

  FarmModel copyWith({
    int?    farmId,
    double? latitude,
    double? longitude,
    String? district,
    String? crop,
    String? cropStage,
    String? riskLevel,
    double? riskProbability,
    String? forecastHorizon,
    String? recommendation,
    String? satelliteTimestamp,
    String? weatherTimestamp,
    String? lastUpdated,
    String? dataNote,
  }) {
    return FarmModel(
      farmId:             farmId             ?? this.farmId,
      latitude:           latitude           ?? this.latitude,
      longitude:          longitude          ?? this.longitude,
      district:           district           ?? this.district,
      crop:               crop               ?? this.crop,
      cropStage:          cropStage          ?? this.cropStage,
      riskLevel:          riskLevel          ?? this.riskLevel,
      riskProbability:    riskProbability    ?? this.riskProbability,
      forecastHorizon:    forecastHorizon    ?? this.forecastHorizon,
      recommendation:     recommendation     ?? this.recommendation,
      satelliteTimestamp: satelliteTimestamp ?? this.satelliteTimestamp,
      weatherTimestamp:   weatherTimestamp   ?? this.weatherTimestamp,
      lastUpdated:        lastUpdated        ?? this.lastUpdated,
      dataNote:           dataNote           ?? this.dataNote,
    );
  }
}
