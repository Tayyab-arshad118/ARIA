import 'package:flutter/material.dart';
import 'aria_theme.dart';

class WelcomeScreen extends StatelessWidget {
  final VoidCallback? getStarted;
  final bool busy;
  final String logoAsset;
  const WelcomeScreen({super.key, required this.getStarted, this.busy = false,
    this.logoAsset = 'assets/aria-logo_new.png'});
  @override
  Widget build(BuildContext context) => AriaPage(child: Column(children: [
    const SizedBox(height: 56),
    Image.asset(logoAsset, width: 210, height: 210, fit: BoxFit.contain, semanticLabel: 'ARIA logo'),
    const SizedBox(height: 24),
    Text('Every word, yours.', textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineMedium),
    const SizedBox(height: 16),
    Text('Your voice, in the languages you love.', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyMedium),
    const SizedBox(height: 40),
    AriaPrimaryButton(label: 'Get started', icon: Icons.arrow_forward, onPressed: getStarted, busy: busy),
  ]));
}
