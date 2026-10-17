# Start ARIA

1. Double-click [Start ARIA.bat](../Start%20ARIA.bat). It prepares dependencies on first run,
   creates protected local connection settings if missing, starts the local server and opens
   the desktop app. No terminal commands or local backend URL/key entry are needed for the
   standard installation. First setup needs Python 3.12 with the Windows `py` launcher and internet.
2. Open the [Colab notebook](../colab/ARIA_Colab_GPU.ipynb), select a GPU, configure your model
   paths and run through cell 6. Keep it running. ARIA cannot start your Colab GPU runtime itself.
3. In ARIA choose **Get started**. Paste the **key from cell 3** and **URL from cell 6** into
   their labelled inputs. You can paste the whole labelled output line, including `COLAB_URL=`.
   These are two different outputs from the same notebook session.
4. Optionally enter a **Groq API key**, or leave it blank to keep the one already configured.
   Choose **Check & connect**. The backend tests your Colab server before saving anything.
   It explains expired URLs, rejected keys, model mismatches and old notebooks. A failed check
   leaves the previous connection intact. Successful credentials are encrypted in local storage.
5. Select a saved voice, or choose **Add a voice** and upload a single-speaker recording.
   Choose **Continue to speaking**, select a language, type, check the preview, and tap **Speak**.

The app opens with your supplied ARIA logo and welcome screen. Connection, voice setup and speaking are separate
screens, with short fade transitions. A centered narrow layout and the same controls are used on desktop and phone-sized screens;
the desktop window starts at 460 × 780 and compacts its spacing on shorter viewports. The gear opens **Connect**; **Change voice** returns to voice setup.
Closing the native app stops the backend started by that launcher. An already-running server is reused
and is not stopped by the launcher. Reopening the launcher while it is already running does not start duplicates.

## Automatic conversion in every model language

With Groq enabled, **Auto-convert** transliterates phonetic/romanized writing into the native script of
the selected language. For example, choose Hindi and type `namaste`. Text already in the target script
is preserved. Latin-script languages retain their normal spelling and accents. Preview and speech use
the same cached conversion; caches are separated by language. Your text is sent to Groq in this mode.
The provider is **Groq**, using a Groq API key; an xAI Grok key is a different provider and is not supported.

**Native script** bypasses conversion and speaks your text as written. If Groq fails for a non-Urdu
language, the app reports the error instead of silently synthesizing unconverted phonetic text. Without
Groq, native-script typing works for all advertised model languages; Urdu additionally has a local dictionary.
Language choices come from the loaded model, so API text conversion does not give the speech model new
language capabilities. Composer input uses transliteration. **Quick phrases translate meaning**:
their cards and speech both follow the shared **Speak in** selector. The original phrase collection is
stored in Urdu, and Groq translates it into your selected language. Translations and audio are cached
separately per language and encrypted locally. Once both are cached, that phrase can play offline.
If translation is unavailable, ARIA reports it instead of speaking the original language unexpectedly.
Editing a phrase edits its original wording; translations refresh after changes.

Speak controls and the bottom navigation stay visible while the screen content scrolls. Background
phrase refreshes preserve existing controls when the collection is unchanged. See the
[updated composer](screenshots/onboarding-compose.png) and [quick phrases](screenshots/quick-phrases-phone.png).

## Reconnecting and troubleshooting

When Colab restarts, its URL and possibly its key change. Open the gear and paste both current outputs.
There is no need to edit environment files. The app never needs the Colab URL in **Advanced · local server**;
that separate panel is only for a custom backend or a phone talking to your laptop.

If the launcher reports a busy port, close the previous manually started backend before launching again.
If startup fails, inspect `startup.log` in your configured ARIA data folder (normally
`%LOCALAPPDATA%\ARIA\data`). Custom environment overrides must point the app and backend to matching
local credentials. The launcher never terminates an unrelated process to free a port.

This change supplies a desktop launcher and a responsive phone layout. It does not install an Android
package or expose the backend to a phone over the network; the existing Android build and LAN setup
instructions remain in the [desktop guide](../aria_desktop/README.md).
