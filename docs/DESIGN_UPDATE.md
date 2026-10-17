# Flat ARIA interface and preview fix

The working app uses Python/Flet with its existing API client and handlers. Its UI now
uses centralized light/dark tokens in [aria_theme.py](../aria_desktop/aria_theme.py),
hairline borders, shadow-free cards, dark pill primary buttons, status pills, language
chips, a compact offline banner and a single message/preview card. The supplied
transparent logo has no tile behind it. The welcome screen consistently uses
“Every word, yours.”

The input-mode menu and language chips delegate to the same handlers as the previous
dropdowns. Voice selection, enrollment, saved phrases, verification, emotion references,
search, playback, connection validation and encrypted settings remain available.
The character limit remains 2000; the design change does not lower it to the example's 500.

Verified at phone size: [English, light](screenshots/speak-english-light.png),
[English, dark](screenshots/speak-english-dark.png), [welcome](screenshots/onboarding-welcome.png),
and [connection](screenshots/onboarding-connect.png). The Python regression suite passed
209 tests, including native-edit isolation, stale-response handling, blur deduplication and
double-tap protection for suggestions. Live Hindi and English previews returned successfully while the voice server
was offline. The logo PNG has an alpha channel with transparent corners.

Non-Urdu preview previously depended on the Colab language check. Known text-preview
languages now use Groq without requiring Colab to be online. Speech still validates the
loaded model's language support. English already written in English normally stays the
same; choose Hindi and type `namaste` to see a script conversion. The composer performs
transliteration, while quick phrases translate their meaning. Native-script mode bypasses
conversion. Failed previews clear stale text and show the error beneath the preview.

The requested [Dart theme and screens](../flutter_ui/README.md) are supplied as presentation
widgets with callback/controller bindings. They are separate from the running Flet app.

## Current logo and independent text fields

The app now uses the user's already-transparent [aria-logo_new.png](../aria_desktop/assets/branding/aria-logo_new.png)
unchanged on the welcome screen, header and voice screen. The same file is bundled in the
Flutter companion. The old generated logo assets and the placeholder A header were removed.
No image generation or background removal was applied to this replacement.

The voice card no longer repeats the header logo or heading. Empty notices and unused
verification controls take no space, and Continue stays in a fixed footer. Short viewports
use tighter spacing and smaller text-area minimums; long content still scrolls with the
wheel, touch or keyboard, without a flashing scrollbar. The compact voice layout was
checked at [360 × 640](screenshots/onboarding-voices-360x640.png).

Each language has a Roman input and a separate editable native-script result, with independent
character counts. Conversion never writes into the Roman field. Editing the native field
cancels pending conversion and uses that edited text for speech in native mode. Editing the
Roman field again resumes automatic conversion. Changing the language resets that override.

Completed or running conversions are not resubmitted by blur. Old responses cannot overwrite
new input or a manual native edit. Suggestion buttons have explicit readable foreground colors
in both themes, and stale/double taps cannot insert a word twice. User-authored repeated words
are preserved; there is no destructive global text deduplication.
