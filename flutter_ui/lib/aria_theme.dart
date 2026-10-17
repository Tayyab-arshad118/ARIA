import 'package:flutter/material.dart';

/// Presentation only: pass your existing controllers and callbacks to the screens.
abstract final class AriaTheme {
  static const accent = Color(0xFF2F6BFF);
  static const duration = Duration(milliseconds: 180);
  static ThemeData light() => _build(false);
  static ThemeData dark() => _build(true);

  static ThemeData _build(bool dark) {
    final colors = AriaColors.forBrightness(dark);
    final scheme = ColorScheme.fromSeed(seedColor: accent,
      brightness: dark ? Brightness.dark : Brightness.light).copyWith(
        primary: accent, surface: colors.card, onSurface: colors.ink,
        outline: colors.border, outlineVariant: colors.border,
        onSurfaceVariant: colors.muted, error: colors.error);
    final outline = RoundedRectangleBorder(borderRadius: BorderRadius.circular(20),
      side: BorderSide(color: colors.border, width: .5));
    return ThemeData(
      useMaterial3: true, colorScheme: scheme, scaffoldBackgroundColor: colors.background,
      extensions: [colors], splashFactory: NoSplash.splashFactory,
      shadowColor: Colors.transparent, dividerColor: colors.border,
      textTheme: TextTheme(
        headlineMedium: TextStyle(fontSize: 30, height: 1.2, fontWeight: FontWeight.w500, color: colors.ink),
        titleLarge: TextStyle(fontSize: 24, fontWeight: FontWeight.w500, color: colors.ink),
        bodyLarge: TextStyle(fontSize: 15, height: 1.5, fontWeight: FontWeight.w400, color: colors.ink),
        bodyMedium: TextStyle(fontSize: 15, height: 1.4, fontWeight: FontWeight.w400, color: colors.muted),
        labelLarge: TextStyle(fontSize: 15, fontWeight: FontWeight.w500, color: colors.ink),
        labelSmall: TextStyle(fontSize: 12, fontWeight: FontWeight.w400, color: colors.muted)),
      cardTheme: CardThemeData(color: colors.card, elevation: 0, margin: EdgeInsets.zero,
        surfaceTintColor: Colors.transparent, shadowColor: Colors.transparent, shape: outline),
      filledButtonTheme: FilledButtonThemeData(style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith((states) => states.contains(WidgetState.disabled) ? colors.soft : colors.ink),
        foregroundColor: WidgetStateProperty.resolveWith((states) => states.contains(WidgetState.disabled) ? colors.muted : colors.background),
        minimumSize: const WidgetStatePropertyAll(Size(48, 54)),
        shape: const WidgetStatePropertyAll(StadiumBorder()),
        elevation: const WidgetStatePropertyAll(0), animationDuration: duration,
        textStyle: const WidgetStatePropertyAll(TextStyle(fontSize: 16, fontWeight: FontWeight.w500)))),
      inputDecorationTheme: InputDecorationThemeData(
        border: InputBorder.none, enabledBorder: InputBorder.none,
        focusedBorder: InputBorder.none, errorBorder: InputBorder.none,
        focusedErrorBorder: InputBorder.none, filled: false,
        floatingLabelBehavior: FloatingLabelBehavior.never,
        contentPadding: const EdgeInsets.symmetric(vertical: 14),
        hintStyle: const TextStyle(fontSize: 15, color: Color(0xFF9A9DAA)),
        errorStyle: TextStyle(fontSize: 12, color: colors.error)),
      chipTheme: ChipThemeData(backgroundColor: colors.card, selectedColor: colors.ink,
        side: BorderSide(color: colors.border, width: .5), shape: const StadiumBorder(),
        elevation: 0, pressElevation: 0, showCheckmark: false,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        labelStyle: TextStyle(fontSize: 15, fontWeight: FontWeight.w400, color: colors.ink),
        secondaryLabelStyle: TextStyle(fontSize: 15, fontWeight: FontWeight.w400, color: colors.background)),
      textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(
        foregroundColor: colors.ink, shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w400))),
      iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(foregroundColor: colors.muted)),
      dividerTheme: DividerThemeData(color: colors.border, thickness: .5, space: 1));
  }
}

@immutable
class AriaColors extends ThemeExtension<AriaColors> {
  final Color background, card, border, ink, muted, soft, success, successBg, warning, warningBg, error, errorBg;
  const AriaColors({required this.background, required this.card, required this.border,
    required this.ink, required this.muted, required this.soft, required this.success,
    required this.successBg, required this.warning, required this.warningBg,
    required this.error, required this.errorBg});
  static AriaColors of(BuildContext context) => Theme.of(context).extension<AriaColors>()!;
  factory AriaColors.forBrightness(bool dark) => AriaColors(
    background: Color(dark ? 0xFF0E0E12 : 0xFFF7F7F9), card: Color(dark ? 0xFF17171C : 0xFFFFFFFF),
    border: Color(dark ? 0xFF26262E : 0xFFE6E6EC), ink: Color(dark ? 0xFFF2F2F5 : 0xFF111218),
    muted: Color(dark ? 0xFFA6A8B5 : 0xFF5B5E6B), soft: Color(dark ? 0xFF222229 : 0xFFF2F3F7),
    success: Color(dark ? 0xFFA8DEC0 : 0xFF17653A), successBg: Color(dark ? 0xFF133323 : 0xFFE8F6EE),
    warning: Color(dark ? 0xFFF0CD83 : 0xFF8A5A00), warningBg: Color(dark ? 0xFF352A14 : 0xFFFFF3DB),
    error: Color(dark ? 0xFFF2ABA3 : 0xFF8E2A20), errorBg: Color(dark ? 0xFF351E20 : 0xFFFFF1F0));
  @override
  AriaColors copyWith({Color? background, Color? card, Color? border, Color? ink,
    Color? muted, Color? soft, Color? success, Color? successBg, Color? warning,
    Color? warningBg, Color? error, Color? errorBg}) => AriaColors(
      background: background ?? this.background, card: card ?? this.card, border: border ?? this.border,
      ink: ink ?? this.ink, muted: muted ?? this.muted, soft: soft ?? this.soft,
      success: success ?? this.success, successBg: successBg ?? this.successBg,
      warning: warning ?? this.warning, warningBg: warningBg ?? this.warningBg,
      error: error ?? this.error, errorBg: errorBg ?? this.errorBg);
  @override
  AriaColors lerp(covariant AriaColors? other, double t) {
    if (other == null) return this;
    Color blend(Color a, Color b) => Color.lerp(a, b, t)!;
    return AriaColors(background: blend(background, other.background), card: blend(card, other.card),
      border: blend(border, other.border), ink: blend(ink, other.ink), muted: blend(muted, other.muted),
      soft: blend(soft, other.soft), success: blend(success, other.success), successBg: blend(successBg, other.successBg),
      warning: blend(warning, other.warning), warningBg: blend(warningBg, other.warningBg),
      error: blend(error, other.error), errorBg: blend(errorBg, other.errorBg));
  }
}

class AriaPage extends StatelessWidget {
  final Widget child;
  final Widget? bottomNavigation;
  const AriaPage({super.key, required this.child, this.bottomNavigation});
  @override
  Widget build(BuildContext context) => Scaffold(body: SafeArea(child: Center(child:
    ConstrainedBox(constraints: const BoxConstraints(maxWidth: 452), child: Column(children: [
      Expanded(child: ScrollConfiguration(behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
        child: SingleChildScrollView(padding: const EdgeInsets.all(16), child: child))),
      if (bottomNavigation != null) Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), child: bottomNavigation!),
    ])))));
}

class AriaPressScale extends StatefulWidget {
  final Widget child;
  const AriaPressScale({super.key, required this.child});
  @override
  State<AriaPressScale> createState() => _AriaPressScaleState();
}
class _AriaPressScaleState extends State<AriaPressScale> {
  bool pressed = false;
  @override
  Widget build(BuildContext context) => Listener(
    onPointerDown: (_) => setState(() => pressed = true),
    onPointerUp: (_) => setState(() => pressed = false),
    onPointerCancel: (_) => setState(() => pressed = false),
    child: AnimatedScale(scale: pressed ? .98 : 1, duration: const Duration(milliseconds: 150), child: widget.child));
}

class AriaPrimaryButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool busy;
  const AriaPrimaryButton({super.key, required this.label, required this.icon, this.onPressed, this.busy = false});
  @override
  Widget build(BuildContext context) => AriaPressScale(child: SizedBox(width: double.infinity, height: 54,
    child: FilledButton.icon(onPressed: busy ? null : onPressed,
      icon: busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : Icon(icon, size: 20),
      label: Text(label))));
}

class AriaHeader extends StatelessWidget {
  final VoidCallback onToggleTheme, onConnect;
  const AriaHeader({super.key, required this.onToggleTheme, required this.onConnect});
  @override
  Widget build(BuildContext context) {
    return Row(children: [Image.asset('assets/aria-logo_new.png', width: 64, height: 64,
      fit: BoxFit.contain, semanticLabel: 'ARIA logo'), const Spacer(),
      IconButton(tooltip: 'Switch appearance', onPressed: onToggleTheme,
        icon: Icon(Theme.of(context).brightness == Brightness.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined)),
      IconButton(tooltip: 'Connect', onPressed: onConnect, icon: const Icon(Icons.settings_outlined))]);
  }
}

class AriaStatusPill extends StatelessWidget {
  final String label;
  final bool connected;
  const AriaStatusPill({super.key, required this.label, required this.connected});
  @override
  Widget build(BuildContext context) {
    final colors = AriaColors.of(context);
    return Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(color: connected ? colors.successBg : colors.warningBg, borderRadius: BorderRadius.circular(100)),
      child: Text(label, style: TextStyle(fontSize: 12, color: connected ? colors.success : colors.warning)));
  }
}

class AriaErrorBanner extends StatelessWidget {
  final String title, detail;
  final VoidCallback onConnect;
  const AriaErrorBanner({super.key, required this.title, required this.detail, required this.onConnect});
  @override
  Widget build(BuildContext context) {
    final colors = AriaColors.of(context);
    return Container(padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: colors.errorBg, borderRadius: BorderRadius.circular(14)),
      child: Row(children: [Icon(Icons.error_outline, color: colors.error, size: 20), const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, color: colors.error)),
          Tooltip(message: detail, child: Text(detail, maxLines: 1, overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 12, color: colors.error)))])), const SizedBox(width: 8),
        TextButton(onPressed: onConnect, style: TextButton.styleFrom(backgroundColor: colors.card, foregroundColor: colors.error),
          child: const Text('Connect', style: TextStyle(fontSize: 12)))]));
  }
}
