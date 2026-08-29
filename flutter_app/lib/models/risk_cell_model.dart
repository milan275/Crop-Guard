// CropGuard AI — Risk cell model for heatmap rendering.

class RiskCellModel {
  final double lat;
  final double lon;
  final int    row;
  final int    col;
  final double riskProbability;
  final String riskLevel;

  const RiskCellModel({
    required this.lat,
    required this.lon,
    required this.row,
    required this.col,
    required this.riskProbability,
    required this.riskLevel,
  });

  factory RiskCellModel.fromJson(Map<String, dynamic> json) {
    return RiskCellModel(
      lat:             (json['lat'] as num).toDouble(),
      lon:             (json['lon'] as num).toDouble(),
      row:             json['row'] as int,
      col:             json['col'] as int,
      riskProbability: (json['risk_probability'] as num).toDouble(),
      riskLevel:       json['risk_level'] as String,
    );
  }
}

class DistrictRiskMap {
  final String          district;
  final List<RiskCellModel> cells;
  final double          meanRisk;
  final double          maxRisk;
  final int?            cellCount;
  final int             horizonDays;
  final String?         timestamp;

  const DistrictRiskMap({
    required this.district,
    required this.cells,
    required this.meanRisk,
    required this.maxRisk,
    this.cellCount,
    required this.horizonDays,
    this.timestamp,
  });

  factory DistrictRiskMap.fromJson(Map<String, dynamic> json) {
    final rawCells = json['cells'] as List<dynamic>? ?? [];
    return DistrictRiskMap(
      district:    json['district'] as String,
      cells:       rawCells.map((c) => RiskCellModel.fromJson(c as Map<String, dynamic>)).toList(),
      meanRisk:    (json['mean_risk'] as num?)?.toDouble() ?? 0.0,
      maxRisk:     (json['max_risk'] as num?)?.toDouble() ?? 0.0,
      cellCount:   json['cell_count'] as int?,
      horizonDays: json['horizon_days'] as int? ?? 0,
      timestamp:   json['timestamp'] as String?,
    );
  }
}
