// CropGuard AI — Offline mode banner.

import 'package:flutter/material.dart';
import 'package:cropguard_ai/l10n/generated/app_localizations.dart';

class OfflineBanner extends StatelessWidget {
  final String? lastUpdated;
  const OfflineBanner({super.key, this.lastUpdated});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context)!;
    return Container(
      width: double.infinity,
      color: Colors.orange.shade700,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          const Icon(Icons.wifi_off, color: Colors.white, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l10n.offlineMessage,
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13),
                ),
                if (lastUpdated != null)
                  Text(
                    '${l10n.lastUpdated}: $lastUpdated',
                    style: const TextStyle(color: Colors.white70, fontSize: 11),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
