import 'package:flutter/material.dart';
import 'aria_theme.dart';

class SpeakScreen extends StatelessWidget {
  final TextEditingController messageController;
  final TextEditingController nativeController;
  final FocusNode? messageFocus;
  final String language, preview, inputMode;
  final Map<String, String> languages;
  final bool backendConnected, voiceConnected, busy, canSpeak, isPlaying, converting;
  final int maxCharacters;
  final String? errorTitle, errorDetail;
  final ValueChanged<String> textChanged, languageChanged, modeChanged;
  final ValueChanged<String> nativeChanged;
  final VoidCallback speakClicked, stopClicked, openConnection, toggleTheme;
  final Widget? bottomNavigation, suggestions;
  const SpeakScreen({super.key, required this.messageController, required this.nativeController,
    required this.nativeChanged, this.messageFocus,
    required this.language, required this.languages, required this.preview, required this.inputMode,
    required this.backendConnected, required this.voiceConnected, required this.textChanged,
    required this.languageChanged, required this.modeChanged, required this.speakClicked,
    required this.stopClicked, required this.openConnection, required this.toggleTheme,
    this.busy = false, this.canSpeak = true, this.isPlaying = false, this.converting = false,
    this.maxCharacters = 2000, this.errorTitle, this.errorDetail, this.bottomNavigation, this.suggestions});
  @override
  Widget build(BuildContext context) {
    final colors = AriaColors.of(context);
    final name = languages[language] ?? language;
    final rtl = {'ur', 'ar', 'fa', 'he'}.contains(language);
    return AriaPage(bottomNavigation: bottomNavigation, child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      AriaHeader(onToggleTheme: toggleTheme, onConnect: openConnection), const SizedBox(height: 16),
      Wrap(spacing: 8, runSpacing: 8, children: [
        AriaStatusPill(label: backendConnected ? 'Backend connected' : 'Backend offline', connected: backendConnected),
        AriaStatusPill(label: voiceConnected ? 'Voice server connected' : 'Voice server offline', connected: voiceConnected)]),
      const SizedBox(height: 24), Text('Speak in', style: Theme.of(context).textTheme.labelSmall),
      const SizedBox(height: 8), Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        for (final code in ['en', 'ur']) AriaPressScale(child: ChoiceChip(
          label: Text(languages[code] ?? (code == 'en' ? 'English' : 'Urdu')),
          selected: language == code, labelStyle: TextStyle(color: language == code ? colors.background : colors.ink),
          onSelected: busy ? null : (_) => languageChanged(code))),
        PopupMenuButton<String>(enabled: !busy, onSelected: languageChanged,
          itemBuilder: (_) => [for (final entry in languages.entries.where((entry) => !{'en', 'ur'}.contains(entry.key)))
            PopupMenuItem(value: entry.key, child: Text(entry.value))],
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
            decoration: BoxDecoration(color: colors.card, border: Border.all(color: colors.border, width: .5), borderRadius: BorderRadius.circular(100)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [Text({'en', 'ur'}.contains(language) ? 'More' : name),
              const SizedBox(width: 4), const Icon(Icons.expand_more, size: 18)])))]),
      const SizedBox(height: 24),
      Card(child: Padding(padding: const EdgeInsets.all(20), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(inputMode == 'auto' ? 'Roman $name input' : '$name input', style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(height: 8),
        TextField(controller: messageController, focusNode: messageFocus, onChanged: textChanged,
          minLines: 3, maxLines: 6, maxLength: maxCharacters, cursorColor: AriaTheme.accent,
          style: TextStyle(fontSize: 22, height: 1.4, fontWeight: FontWeight.w400, color: colors.ink),
          decoration: const InputDecoration(hintText: 'Write your message…', counterText: '', contentPadding: EdgeInsets.zero)),
        if (suggestions != null) suggestions!, const SizedBox(height: 16), const Divider(), const SizedBox(height: 16),
        Row(children: [Expanded(child: Text('$name native text', style: const TextStyle(color: AriaTheme.accent, fontSize: 12))),
          ValueListenableBuilder<TextEditingValue>(valueListenable: nativeController, builder: (_, value, child) =>
            Text('${value.text.characters.length} / $maxCharacters', style: Theme.of(context).textTheme.labelSmall))]),
        const SizedBox(height: 8),
        TextField(controller: nativeController, onChanged: nativeChanged, minLines: 2, maxLines: 5,
          maxLength: maxCharacters, textDirection: rtl ? TextDirection.rtl : TextDirection.ltr,
          textAlign: rtl ? TextAlign.right : TextAlign.left,
          style: TextStyle(fontSize: 20, height: 1.5, color: colors.ink),
          decoration: InputDecoration(hintText: 'Converted $name text appears here', counterText: '', contentPadding: EdgeInsets.zero)),
        if (converting) Text('Converting…', style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(height: 16), Row(children: [
          PopupMenuButton<String>(enabled: !busy, onSelected: modeChanged,
            itemBuilder: (_) => const [PopupMenuItem(value: 'auto', child: Text('Auto-convert')),
              PopupMenuItem(value: 'native', child: Text('Native script'))],
            child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(color: colors.soft, borderRadius: BorderRadius.circular(100)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [Text(inputMode == 'auto' ? 'Auto-convert' : 'Native script', style: const TextStyle(fontSize: 12)),
                const Icon(Icons.expand_more, size: 16)]))), const Spacer(),
          ValueListenableBuilder<TextEditingValue>(valueListenable: messageController, builder: (_, value, child) =>
            Text('${value.text.characters.length} / $maxCharacters', style: Theme.of(context).textTheme.labelSmall))]),
      ]))), const SizedBox(height: 24),
      Row(children: [Expanded(child: AriaPrimaryButton(label: 'Speak', icon: Icons.volume_up_outlined,
        onPressed: canSpeak ? speakClicked : null, busy: busy)), const SizedBox(width: 16),
        SizedBox(width: 54, height: 54, child: IconButton(onPressed: isPlaying ? stopClicked : null, tooltip: 'Stop',
          style: IconButton.styleFrom(backgroundColor: colors.card, shape: CircleBorder(side: BorderSide(color: colors.border, width: .5))),
          icon: const Icon(Icons.stop_outlined)))]),
      if (!voiceConnected || errorTitle != null) ...[const SizedBox(height: 24),
        AriaErrorBanner(title: errorTitle ?? 'Voice server is offline', detail: errorDetail ?? 'Reconnect to start speaking.', onConnect: openConnection)],
    ]));
  }
}
