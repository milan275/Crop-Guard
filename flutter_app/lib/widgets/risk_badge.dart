// CropGuard AI — Risk level badge widget.

import 'package:flutter/material.dart';
import '../utils/constants.dart';

class RiskBadge extends StatelessWidget {
  final String? riskLevel;
  final double? probability;
  final double fontSize;

  const RiskBadge({
    super.key,
    this.riskLevel,
    this.probability,
    this.fontSize = 14,
  });

  Color get _color {
    if (riskLevel == null) return Colors.grey;
    final hex = AppConstants.riskColours[riskLevel!.toUpperCase()];
    return hex != null ? Color(hex) : Colors.grey;
  }

  @override
  Widget build(BuildContext context) {
    final label = riskLevel ?? 'UNKNOWN';
    final probText = probability != null
        ? ' (${(probability! * 100).toStringAsFixed(0)}%)'
        : '';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: _color.withOpacity(0.15),
        border: Border.all(color: _color, width: 1.5),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        '$label$probText',
        style: TextStyle(
          color: _color,
          fontWeight: FontWeight.bold,
          fontSize: fontSize,
        ),
      ),
    );
  }
}
