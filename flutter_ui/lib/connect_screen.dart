import 'package:flutter/material.dart';
import 'aria_theme.dart';

class ConnectScreen extends StatefulWidget {
  final TextEditingController keyController, urlController, groqController;
  final VoidCallback saveColab, showVoices, openSettings, toggleTheme, openConnection;
  final bool busy;
  final String? keyError, urlError, groqError, connectionError;
  const ConnectScreen({super.key, required this.keyController, required this.urlController,
    required this.groqController, required this.saveColab, required this.showVoices,
    required this.openSettings, required this.toggleTheme, required this.openConnection,
    this.busy = false, this.keyError, this.urlError, this.groqError, this.connectionError});
  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}
class _ConnectScreenState extends State<ConnectScreen> {
  bool hideKey = true, hideGroq = true;
  // Controllers and connection state remain owned by the caller. Only visibility is local.
  @override
  Widget build(BuildContext context) => AriaPage(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
    AriaHeader(onToggleTheme: widget.toggleTheme, onConnect: widget.openConnection), const SizedBox(height: 24),
    Text('Connect your voice server', style: Theme.of(context).textTheme.titleLarge), const SizedBox(height: 8),
    Text('Paste the two outputs from your running Colab notebook.', style: Theme.of(context).textTheme.bodyMedium),
    const SizedBox(height: 24),
    Card(child: Padding(padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8), child: Column(children: [
      TextField(controller: widget.keyController, enabled: !widget.busy, obscureText: hideKey,
        autocorrect: false, enableSuggestions: false,
        decoration: InputDecoration(hintText: 'Key from cell 3', errorText: widget.keyError,
          suffixIcon: IconButton(tooltip: hideKey ? 'Show key' : 'Hide key',
            onPressed: () => setState(() => hideKey = !hideKey), icon: Icon(hideKey ? Icons.visibility_outlined : Icons.visibility_off_outlined)))),
      const Divider(), TextField(controller: widget.urlController, enabled: !widget.busy,
        keyboardType: TextInputType.url, autocorrect: false,
        decoration: InputDecoration(hintText: 'URL from cell 6', errorText: widget.urlError)),
      const Divider(), TextField(controller: widget.groqController, enabled: !widget.busy,
        obscureText: hideGroq, autocorrect: false, enableSuggestions: false,
        decoration: InputDecoration(hintText: 'Groq key (optional)', errorText: widget.groqError,
          suffixIcon: IconButton(tooltip: hideGroq ? 'Show Groq key' : 'Hide Groq key',
            onPressed: () => setState(() => hideGroq = !hideGroq), icon: Icon(hideGroq ? Icons.visibility_outlined : Icons.visibility_off_outlined)))),
      if (widget.connectionError != null) Padding(padding: const EdgeInsets.only(bottom: 12), child:
        Align(alignment: Alignment.centerLeft, child: Text(widget.connectionError!, style: TextStyle(fontSize: 12, color: AriaColors.of(context).error)))),
    ]))), const SizedBox(height: 24),
    AriaPrimaryButton(label: 'Check & connect', icon: Icons.link, onPressed: widget.saveColab, busy: widget.busy),
    const SizedBox(height: 16),
    ListTile(contentPadding: const EdgeInsets.symmetric(horizontal: 8), title: const Text('Use saved voices offline'),
      trailing: const Icon(Icons.chevron_right), onTap: widget.busy ? null : widget.showVoices),
    ListTile(contentPadding: const EdgeInsets.symmetric(horizontal: 8), title: const Text('Advanced'),
      trailing: const Icon(Icons.chevron_right), onTap: widget.busy ? null : widget.openSettings),
    const SizedBox(height: 8), Text('Groq converts your text when enabled. Leave its key blank to keep the saved one.',
      style: Theme.of(context).textTheme.labelSmall),
  ]));
}
