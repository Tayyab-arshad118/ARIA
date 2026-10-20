# Flet desktop application

[Project handbook](../README.md)

This folder contains the working user interface. It is Python/Flet, pinned to Flet 0.28.3 and flet-audio 0.1.0. It talks only to the local backend; it does not load the speech model or call Groq/Colab directly.

## Files

| Item | Purpose |
| --- | --- |
| [aria_app.py](aria_app.py) | Entry point, app settings, backend client, UI state, screens, dialogs, and playback. |
| [aria_theme.py](aria_theme.py) | Centralized light/dark tokens, flat cards, buttons, fields, and status pills. |
| [assets](assets/) | Current logo and bundled Urdu font/license. |
| [tests](tests/README.md) | UI/state/API contract tests and screenshot tools. |
| [.env.example](.env.example) | Local backend connection and client limits/timeouts. |
| [requirements.txt](requirements.txt) | Desktop runtime packages. |
| [pyproject.toml](pyproject.toml) | Flet build metadata, entry point, dependencies, exclusions, Android network configuration. |

## Run

The usual Windows entry point is [Start ARIA.bat](../Start%20ARIA.bat), which also starts the backend. With a backend already running, from the repository root:

```powershell
.\.venv\Scripts\python.exe aria_desktop/aria_app.py
```

The app defaults to local port 8001. Settings come from explicit `ARIA_APP_ENV_FILE`, otherwise a private desktop environment file, otherwise this directory's `.env`. Process variables override the chosen file. Match `ARIA_KEY` to the local backend.

## Screens and controls

The governing purpose is speech-free assistive communication. See the [implementation and evaluation guide](../README.md#chapter-20--fyp-implementation-migration-and-evaluation). Normal access uses the device key and optional PIN, never a spoken challenge. Expression and protected output are implemented; model quality and accessibility still need real-user evaluation.

- **Welcome:** supplied logo, one tagline, and Get started on the first setup; later launches open Speak.
- **Connect:** Colab key and URL, optional Groq key, checked connection, and quieter Advanced/offline actions.
- **Your voice:** patient/helper setup, saved voice selection, historical-recording registration, authorized emotion references, research-only spoken checks, and a fixed Continue button.
- **Compose:** language selection, independent Roman/native text fields, suggestions, playback controls, and connection/error status.
- **Phrases:** translated cards, language selection, search/filter, favorites, recents, editing, and playback. Phrase text remains visible without an authorized voice.
- **Profile:** PIN/recovery, trusted helper permissions, voice data, and connection access.

The header logo is not repeated in the voice card. The default desktop window is 440 × 820, centered content is constrained, and shorter viewports reduce spacing/text-area minimums. Long content remains scrollable without visible scrollbars. Font sizing, contrast, and the separate source/native text flows are preserved across light/dark appearances. A private local marker records only that setup was completed; it contains no key or voice data.

## State and event behavior

`AppSettings` contains client configuration. `BackendClient` wraps HTTP calls, payloads, bounded responses, safe errors, and optional session headers. `AriaApp` owns the controls and tasks.

Typing schedules a debounced preview. Revisions prevent late responses from replacing newer input. Completed/running conversions are not resubmitted merely because the field loses focus. Suggestions use their original text/revision so double or stale taps cannot append a word twice.

Native editing cancels pending conversion, keeps the Roman field unchanged, and selects native mode for that speech request. Editing the Roman field or changing language resets that override. The two fields never mirror each other's edits in a loop.

Playback uses a fresh audio control per WAV and releases the old one. Stop affects playback, not a remote request already running. UI shutdown cancels local tasks and closes the client; it cannot guarantee cancellation of remote GPU work.

## Connect versus Advanced

Connect accepts Colab/Groq values and forwards them to the backend for checking/encrypted storage. Advanced changes the app's own backend address/bearer key for the current app session. Never put the Colab URL into the backend-address field.

On a phone, localhost means the phone. A laptop-hosted backend needs deliberate LAN binding/auth/host/firewall setup. Responsive desktop design and build metadata are not a tested Android installation.

## Development and verification

### Shared assets and font license

The app's [assets directory](assets/) contains the already-transparent user-supplied [ARIA logo](assets/branding/aria-logo_new.png) and [Noto Nastaliq Urdu font](assets/fonts/NotoNastaliqUrdu.ttf). The logo appears on Welcome and in the header; it is not repeated in the voice card. Paths are relative to the asset root, with `FLET_ASSETS_DIR` available for packaged runtime locations.

The font is the unmodified Google Fonts `NotoNastaliqUrdu[wght].ttf`, renamed locally. Copyright 2022 The Noto Project Authors; keep the [SIL Open Font License](assets/fonts/OFL.txt) with every redistributed copy. Its recorded SHA-256 is `98a4787f34eb6fde57fb9a1121a8f216301196ab0da98ea110cad581be8abbcd`. If unavailable, platform font fallback can change shaping/appearance. [Font source](https://github.com/google/fonts/tree/main/ofl/notonastaliqurdu)

Assets are not storage for private recordings or keys. Inspect replacements in light/dark themes and at small sizes; do not stretch the logo or remove font licensing material.

### Optional Android packaging

Build from this directory, not from the repository root, so sibling backend data cannot be included accidentally. From the repository root in Windows PowerShell:

```powershell
Set-Location aria_desktop
..\.venv\Scripts\flet.exe build apk
```

On Linux/macOS, enter this directory and use `../.venv/bin/flet build apk`. The pinned Flet build tool needs its Flutter/Android/Python build dependencies, network access, disk space, and the required SDK/JDK setup. Build output goes under `build/apk`. An APK/device acceptance result is not supplied by this documentation change.

Keep the build's environment/test/cache exclusions and bundled font license. A phone client needs the laptop's reachable backend address and matching local bearer key in Advanced; localhost on the phone is not the laptop. The existing Android manifest allows cleartext HTTP for local testing, which does not encrypt token/audio traffic. Use HTTPS for an untrusted network.

If a picker returns an unreadable cloud/content URI, save the recording locally and select it again. The app does not include microphone capture. OS picker/audio components may use their own caches even though application playback does not intentionally export WAV files.

### Automated checks

```powershell
.\.venv\Scripts\python.exe -m pytest aria_desktop/tests -q
```

Keep service logic in the backend, UI tokens in the theme, and user interaction in the app. Update matching client contracts when changing API payloads. Preserve the asset/license exclusions in packaging and check both normal and short viewports after changing layout.

## Assistive controls

The voice entry offers Use ARIA Voice and Use My Voice. The generic provider shows an honest not-configured state until its licensed reference is installed. The account control supports PINs, scoped caregivers and recovery. Enrollment and emotion uploads record exact-file authorization. Expression is available for messages and phrases, with visible neutral fallback. Playback rejects unverified normal-policy audio; Copy message preserves a text alternative.
