// CropGuard AI — flutter_map layer that renders the risk heatmap grid.
//
// Each risk cell is drawn as a coloured rectangle on the map.
// Colour is determined by risk level (LOW/MODERATE/HIGH/CRITICAL).

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../models/risk_cell_model.dart';
import '../utils/constants.dart';

class RiskHeatmapLayer extends StatelessWidget {
  final List<RiskCellModel> cells;
  final double cellSizeDeg;
  final void Function(RiskCellModel)? onCellTap;

  const RiskHeatmapLayer({
    super.key,
    required this.cells,
    this.cellSizeDeg = 0.05,
    this.onCellTap,
  });

  Color _cellColor(String riskLevel, double prob) {
    final hex = AppConstants.riskColours[riskLevel.toUpperCase()];
    final base = hex != null ? Color(hex) : Colors.grey;
    // Opacity scales with probability for a smoother gradient
    return base.withOpacity(0.35 + prob * 0.50);
  }

  @override
  Widget build(BuildContext context) {
    final half = cellSizeDeg / 2;

    return PolygonLayer(
      polygons: cells.map((cell) {
        return Polygon(
          points: [
            LatLng(cell.lat - half, cell.lon - half),
            LatLng(cell.lat - half, cell.lon + half),
            LatLng(cell.lat + half, cell.lon + half),
            LatLng(cell.lat + half, cell.lon - half),
          ],
          color: _cellColor(cell.riskLevel, cell.riskProbability),
          borderColor: Colors.transparent,
          borderStrokeWidth: 0,
          isFilled: true,
        );
      }).toList(),
    );
  }
}

// Legend widget displayed below or beside the map.
class RiskLegend extends StatelessWidget {
  const RiskLegend({super.key});

  @override
  Widget build(BuildContext context) {
    const levels = ['LOW', 'MODERATE', 'HIGH', 'CRITICAL'];
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.90),
        borderRadius: BorderRadius.circular(8),
        boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 4)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('Risk Level', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
          const SizedBox(height: 4),
          ...levels.map((level) {
            final hex = AppConstants.riskColours[level]!;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  Container(
                    width: 14, height: 14,
                    decoration: BoxDecoration(
                      color: Color(hex).withOpacity(0.7),
                      borderRadius: BorderRadius.circular(3),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(level, style: const TextStyle(fontSize: 11)),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }
}
