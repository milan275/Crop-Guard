// CropGuard AI — basic smoke test.
// Full integration tests require a running backend.

import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard_ai/main.dart';

void main() {
  testWidgets('App starts without crashing', (WidgetTester tester) async {
    // Pump the app — CacheService.init() is skipped in test mode
    // so we just verify the widget tree builds.
    await tester.pumpWidget(const CropGuardApp());
    expect(find.byType(CropGuardApp), findsOneWidget);
  });
}
