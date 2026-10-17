# ARIA Flutter presentation widgets

The running workspace app is Python/Flet, not a Dart/Flutter application. Its existing
controllers, routes and API clients are preserved. These full Dart files are an additional
UI-only implementation of the requested screens; they do not replace the working app.

- [Theme and shared widgets](lib/aria_theme.dart)
- [Welcome](lib/welcome_screen.dart)
- [Speak](lib/speak_screen.dart)
- [Connect](lib/connect_screen.dart)

Use these with a recent Flutter SDK supporting `CardThemeData` and `InputDecorationThemeData`
(Dart 3.9 or later). Attach your existing `TextEditingController`, focus node, state values,
and callbacks. The widgets do not create API clients, modify credentials, dispose caller-owned
controllers, translate text, or synthesize audio. Rebuild with the updated preview and status
from your existing state-management system. Pass existing navigation and suggestion widgets
through the optional slots, so those capabilities remain available.

```dart
MaterialApp(
  theme: AriaTheme.light(),
  darkTheme: AriaTheme.dark(),
  themeMode: yourExistingThemeMode,
  home: yourExistingRouterOrScreen,
);
```

The example above shows the theme attachment point, not replacement state-management code.
For Speak, wire `textChanged`, `languageChanged`, `modeChanged`, `speakClicked`, `stopClicked`,
`openConnection`, and `toggleTheme` to the existing callbacks. Pass the existing limit via
`maxCharacters` (default 2000, matching the working app). For Connect, pass the three existing
controllers plus `saveColab`, `showVoices`, `openSettings`, and the header callbacks. Validation
messages are supplied as `keyError`, `urlError`, `groqError`, and `connectionError`.

Flutter/Dart is not installed in this workspace, so these companion widgets have not been
compiled here. The running Python/Flet UI is tested separately. With Flutter available,
run `flutter pub get` and `flutter analyze` in this directory before integrating.

Theme API references: [ThemeData](https://api.flutter.dev/flutter/material/ThemeData-class.html),
[CardThemeData](https://api.flutter.dev/flutter/material/CardThemeData-class.html),
[InputDecorationThemeData](https://api.flutter.dev/flutter/material/InputDecorationThemeData-class.html).

## Independent native editor

`SpeakScreen` now also takes a separate caller-owned `nativeController` and `nativeChanged`
callback. Write conversion results to that controller only. In the native edit handler,
invalidate pending conversion, preserve `messageController.text`, and tell your existing speech
handler to use native text with native input mode. Updating the Roman controller resumes
conversion. Do not mirror native edits back into the Roman controller. The running Flet app
implements and tests these rules; the Dart widgets leave that state in the caller's ownership.

All Flutter branding now uses the supplied `assets/aria-logo_new.png` unchanged.
