# A.R.I.A — Flet app (Phases 3–5)

The application entry point is [aria_app.py](aria_app.py), with centralized styling in
[aria_theme.py](aria_theme.py), pinned to
**Flet 0.28.3** and **flet-audio 0.1.0**. It talks only to the Phase 2 local backend.
It never calls Colab or Groq directly and contains no model, database, or GPU dependency.
See the [Phase 4 guide](../PHASE4.md) for the quick-phrase grid, favorites/recents,
phrase editor, prepared playback, suggestion chips, new API contracts and test commands.
The [Phase 5 guide](../PHASE5.md) explains the optional Verify voice and Emotion reference
dialogs. Strict mode requires verification before either typed or quick-phrase speech.
Session tokens stay in memory and are sent only in headers to the configured backend.

The latest [flat design](../docs/DESIGN_UPDATE.md) uses light/dark tokens, a transparent logo,
status and language pills, a single message card, and a matching dark-mode toggle,
separate Compose/Phrases views, responsive cards and phrase search. See the
[current setup/security guide](../UI_AND_SECURITY.md) for private configuration discovery;
when private configuration exists it takes precedence over the project `.env` file.
**Add a voice → Choose audio** also accepts MP3, M4A, AAC, OGG and FLAC and converts them
to WAV automatically on the local backend. Verification recordings still require WAV.

## Files

```text
aria_desktop/
├── aria_app.py                     # Full UI, async backend client, and playback
├── pyproject.toml                  # Isolated Android build configuration
├── requirements.txt               # Pinned Flet/audio plus HTTP and dotenv support
├── .env.example                    # App connection and behavior settings
├── .gitignore
├── assets/fonts/
│   ├── NotoNastaliqUrdu.ttf         # Bundled, no font download during use
│   ├── OFL.txt                     # Required font redistribution license
│   └── README.md
├── tests/test_desktop.py           # Pinned controls, HTTP contracts, and async behavior
└── README.md
```

## Run on desktop

For Windows, use [Start ARIA.bat](../Start%20ARIA.bat). It starts the local backend and desktop
app together. Paste your two Colab outputs into **Connect** in the app; see the
[simple startup guide](../docs/EASY_START.md). Manual development commands follow below.

Start the [local backend](../aria_backend/README.md) in its own terminal. For real speech,
start the [Colab notebook](../colab/ARIA_Colab_GPU.ipynb), configure its URL/key in the
backend, and keep it running. Preview works without Colab with local conversion enabled.

Windows PowerShell, from the repository root:

```powershell
# Skip venv creation if you already completed Phases 1–2.
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r aria_desktop/requirements.txt
# Copy once; do not overwrite an existing app .env.
Copy-Item aria_desktop/.env.example aria_desktop/.env
.\.venv\Scripts\python.exe aria_desktop/aria_app.py
```

Linux/macOS, from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r aria_desktop/requirements.txt
cp -n aria_desktop/.env.example aria_desktop/.env
.venv/bin/python aria_desktop/aria_app.py
```

On Linux the native file picker may need Zenity (`sudo apt install zenity` on Debian/Ubuntu).
Desktop runtime prerequisites vary by OS; see the
[Flet 0.28.3 file-picker implementation](https://github.com/flet-dev/flet/blob/v0.28.3/sdk/python/packages/flet/src/flet/core/file_picker.py).

The app defaults to `http://127.0.0.1:8001`. In the app's own `.env`, set
`ARIA_BACKEND_URL` to the local backend origin and `ARIA_KEY` to the backend's optional
bearer token. **Do not enter the Colab URL, Colab API key, or Groq key into this app.**
The separate backend environment remains in its own directory. Environment variables
take precedence over the app's `.env`.

## Use the app

1. Choose **Add a voice**, enter a name, and select a recording of one speaker, up to
   30 minutes / 256 MiB. WAV, MP3, M4A, AAC, OGG and FLAC are accepted. The local backend
   scans the recording and sends a suitable section of up to 30 seconds to Colab for voice latents.
2. Select your enrolled voice. Profiles marked as needing re-enrollment cannot speak.
   The refresh button reloads voices and connection status after backend changes.
3. Select a **Language** advertised by your running model. **Auto-convert** uses Groq to
   convert phonetic typing into that language's script; **Native script** bypasses conversion.
   The preview updates after a 450 ms typing pause
   and immediately on blur. Old responses cannot overwrite newer typing. In explicit
   Urdu mode the typed script is previewed locally; no transliteration request is needed.
4. Choose a speed from 0.5× to 2.0× and tap the large **Speak** button. The app plays
   the returned WAV through a **new `flet_audio.Audio` control for every playback**.
   Previous controls are stopped/released and removed. **Stop** stops playback; it does
   not cancel an in-progress GPU synthesis request.
5. Open the settings gear to change the backend address/key without restarting. These
   changes last only for the current app session. The app does not write settings or
   keys to device storage; set your environment file for desktop persistence.

The UI has light/dark appearances, large buttons, a right-aligned Nastaliq preview, selectable text,
and plain-language errors. Urdu input is also right-aligned when detected or explicitly
selected. At smaller widths the page scrolls and dialog actions wrap. The bundled font
is registered through `page.fonts`; missing desktop assets fall back to the platform font.

**Microphone recording is an optional future extra**, explicitly labeled in enrollment.
No recording control or microphone permission is included. Record a WAV in another app
and select it here. A canceled picker leaves the current selection unchanged; an invalid
replacement clears it. If Android returns a non-readable cloud/content URI, save the
recording locally in Downloads and select it again.

The app keeps generated WAV bytes in memory for playback and creates no audio files.
The Flet/audio engine or Android picker may use OS-managed caches; this is not a promise
of secure memory erasure or control over platform caching. The backend owns voice/profile
storage and deletion; see its privacy statement. This phase does not add a delete-data UI.

## Settings

All configurable values are documented in [.env.example](.env.example).

| Setting | Default | Purpose |
| --- | --- | --- |
| `ARIA_BACKEND_URL` | `http://127.0.0.1:8001` | Backend origin, no credentials/query/path |
| `ARIA_KEY` | Empty | Optional backend bearer token |
| `ARIA_PREVIEW_DELAY_MS` | 450 | Typing debounce |
| `ARIA_REQUEST_TIMEOUT_SECONDS` | 300 | Long synthesis/enrollment timeout |
| `ARIA_CONNECT_TIMEOUT_SECONDS` | 5 | Connection timeout |
| `ARIA_MAX_TEXT_CHARS` | 2000 | Match the backend's input limit |
| `ARIA_MAX_UPLOAD_BYTES` | 268435456 | Maximum source recording size (256 MiB) |
| `ARIA_MAX_AUDIO_BYTES` | 33554432 | Bound received audio memory |
| `ARIA_DEFAULT_SPEED` | 1.0 | Initial synthesis speed |
| `ARIA_AUDIO_LOAD_TIMEOUT_SECONDS` | 20 | Playback initialization watchdog |
| `ARIA_PREDICT_DELAY_MS` | 120 | Roman suggestion debounce |
| `ARIA_PHRASE_REFRESH_SECONDS` | 10 | Refresh phrase readiness while idle |

Requests use an async HTTPX client, with no redirect following or automatic retries.
The app sends `Authorization: Bearer ...` only to the configured backend. It does not
display upstream error bodies or log user text, recordings, audio, or keys. Changing a
connection replaces the client and cancels pending preview work. API-key fields are
masked and keys are excluded from configuration-object representations.

The preview is transliteration; the spoken-text preview returned after synthesis also
includes the backend's normalization (such as numbers expanded into words). If you edit
while synthesis is running, the old synthesis response cannot replace the new preview.
Rule-based transliteration can be inaccurate; use corrected Urdu script when necessary.

## Build an Android APK later

Build from this isolated directory so the app package cannot include the sibling backend,
its SQLite database, voice profiles, or Colab notebook. [pyproject.toml](pyproject.toml)
sets the entry module to `aria_app`, includes `flet-audio`, and excludes `.env`, `.env.*`,
test code, virtual environments, and bytecode. Never move the backend data into this folder.
The bundled font and its license remain in the assets directory.

Install the requirements above, then from the repository root:

```powershell
Set-Location aria_desktop
..\.venv\Scripts\flet.exe build apk
```

Linux/macOS:

```bash
cd aria_desktop
../.venv/bin/flet build apk
```

The command uses Flet 0.28.3's Android build toolchain and produces output under `build/apk`.
It needs network access to obtain Flutter/Android/Python packages, sufficient disk space,
and the Android SDK/JDK prerequisites. Follow the build command's prerequisite guidance.
See [Flet Android packaging](https://flet.dev/docs/publish/android/) and the
[pinned 0.28.3 build command](https://github.com/flet-dev/flet/blob/v0.28.3/sdk/python/packages/flet-cli/src/flet_cli/commands/build.py)
if current documentation differs from the pinned release.

After installing the APK, use Connection settings to enter the **laptop's LAN IP**, for
example `http://192.168.1.10:8001`. **127.0.0.1 on a phone refers to the phone, not the laptop.**
On the laptop, set backend `HOST=0.0.0.0`, configure `ARIA_KEY`, restart the backend,
and allow its port through the firewall on your private LAN. Both devices must be on
the same reachable network. Phone settings are session-only; enter them again after
relaunching the app.

The testing manifest requests Internet permission and allows cleartext HTTP for the
local LAN backend. HTTP does not encrypt your token/audio over the LAN; use an HTTPS
backend origin on untrusted networks. No microphone/storage-wide permissions are added.
The manifest configuration is supported by the
[0.28.3 Android template](https://github.com/flet-dev/flet-build-template/blob/0.28.3/%7B%7Bcookiecutter.out_dir%7D%7D/android/app/src/main/AndroidManifest.xml).

An APK build/device test has **not** been performed in this workspace: Flutter and adb
were not available on PATH. Native audio output and Android file-picker behavior still
require device acceptance testing. This phase supplies the build configuration and exact
commands; it does not claim a tested APK artifact.

## Verification and checklist

Verified on Python 3.12: **32 app tests passed; 113 tests passed across all three phases**.
Compilation and `pip check` passed. The combined suite reported the existing non-failing
Starlette TestClient/httpx deprecation warning from earlier phases.

From the repository root, after installing the app and test dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q aria_desktop/tests
# Full repository checks after also installing both earlier phases' requirements:
.\.venv\Scripts\python.exe -m pytest -q
```

The automated suite uses real pinned Flet controls with a fake native page, mocked HTTP,
and synthetic WAVs. It checks debounce/blur, stale responses, voice selection and model
mismatch, enrollment/cancellation, settings updates, safe errors, response limits,
WAV validation, and creation/release of a fresh audio control for every playback.
The interface was additionally rendered in Flet's browser preview against the real local
backend to check Urdu conversion, the bundled font, connection state and phone-width dialogs.
Browser preview is a layout check; native file selection/playback remains the target.

Before using your real voice:

- Start backend + Colab and verify “voice server ready”.
- Enroll a suitable WAV and verify the new profile is selected.
- Type `mujhe pani chahiye`; verify `مجھے پانی چاہیے` appears after a pause and on blur.
- Speak Roman and Urdu inputs, adjust speed, repeat playback, and test Stop.
- Interrupt backend connectivity and verify the message offers a useful next step.
- Change Connection settings and verify refresh/preview use the new backend.
- On a phone, verify LAN access, font shaping, WAV selection, playback and scrolling.

## Troubleshooting

- **Backend unreachable:** start it, verify its port, and check the app's address. The
  connection should point to the local backend, not the changing Colab URL.
- **Key rejected:** the app key must match backend `ARIA_KEY`. Colab/Groq keys belong
  only in the backend environment. Update the masked field in Connection settings.
- **Speak disabled:** enter text and choose a compatible enrolled voice. A profile from
  an older model needs a new recording.
- **No audio:** check system volume/output, wait for the audio-loaded status, and try
  another short message. The load watchdog reports failures to initialize playback.
- **Font missing:** restore the bundled font under `assets/fonts`; the UI still runs
  with the platform fallback font.
- **APK dependency errors:** keep both Flet and its CLI at 0.28.3 and flet-audio at 0.1.0;
  do not upgrade only one package. Build from this directory using the supplied metadata.

The app expects the single-user backend with the Phase 4/5 contracts. Quick phrases,
favorites/recents, prediction and optional safety workflows are implemented. Native audio
and Android device acceptance checks still require your own runtime and model setup.
