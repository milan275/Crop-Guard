// CropGuard AI — Admin override model.

class OverrideModel {
  final int?    id;
  final double  bottomLeftLat;
  final double  bottomLeftLon;
  final double  topRightLat;
  final double  topRightLon;
  final double  overridePrediction;
  final String? overrideSuggestion;
  final bool    active;
  final String? createdAt;

  const OverrideModel({
    this.id,
    required this.bottomLeftLat,
    required this.bottomLeftLon,
    required this.topRightLat,
    required this.topRightLon,
    required this.overridePrediction,
    this.overrideSuggestion,
    this.active = true,
    this.createdAt,
  });

  factory OverrideModel.fromJson(Map<String, dynamic> json) {
    return OverrideModel(
      id:                 json['id'] as int?,
      bottomLeftLat:      (json['bottom_left_lat'] as num).toDouble(),
      bottomLeftLon:      (json['bottom_left_lon'] as num).toDouble(),
      topRightLat:        (json['top_right_lat'] as num).toDouble(),
      topRightLon:        (json['top_right_lon'] as num).toDouble(),
      overridePrediction: (json['override_prediction'] as num).toDouble(),
      overrideSuggestion: json['override_suggestion'] as String?,
      active:             json['active'] as bool? ?? true,
      createdAt:          json['created_at'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
    'bottom_left_lat':     bottomLeftLat,
    'bottom_left_lon':     bottomLeftLon,
    'top_right_lat':       topRightLat,
    'top_right_lon':       topRightLon,
    'override_prediction': overridePrediction,
    'override_suggestion': overrideSuggestion,
  };
}
