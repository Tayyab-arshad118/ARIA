# Desktop tests and visual checks

[Project handbook](../../README.md) · [Desktop folder](../README.md)

This folder verifies the client and UI without requiring a real native window, enrolled speaker, or GPU. Tests use real pinned Flet controls with fake page/client objects and mock HTTP transports.

## Files

| File | Coverage |
| --- | --- |
| [test_desktop.py](test_desktop.py) | Settings, backend contracts, debouncing, field modes, playback lifecycle, enrollment, connection settings, phrases, verification, appearance, and navigation. |
| [test_onboarding.py](test_onboarding.py) | Colab output parsing, welcome/connect/voice flow, language controls, and stable translated phrase rendering. |
| [test_native_editor.py](test_native_editor.py) | Independent native edits, stale-result rejection, blur deduplication, double-tap protection, and script-specific fields. |
| [capture_flow.py](capture_flow.py) | Captures the real onboarding/compose/phrase UI at a chosen viewport using a local preview and headless Edge. |
| [capture_ui.py](capture_ui.py) | Earlier general light/dark/mobile capture helper; some semantic targets reflect an older layout. |

## Automated checks

From the repository root, with desktop and test dependencies installed:

```powershell
.\.venv\Scripts\python.exe -m pytest aria_desktop/tests -q
.\.venv\Scripts\python.exe -m pytest aria_desktop/tests/test_native_editor.py -q
```

Tests should keep source and native controls independent, preserve existing callback contracts, and simulate late network results. Do not replace those behaviors with tests that only check a label or mirror implementation details.

## Visual captures

The Windows capture helpers expect a running loopback Flet web preview on port 8550 and Microsoft Edge at the path in the script. To start a development preview from the repository root, in its own terminal:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'aria_desktop'); import aria_app as a; a.ft.app(target=a.main, assets_dir=str(a.ASSETS), host='127.0.0.1', port=8550, view=None)"
```

With the local backend available, use another terminal:

```powershell
.\.venv\Scripts\python.exe aria_desktop/tests/capture_flow.py --width 360 --height 640
```

The helper uses an isolated Edge profile, accesses the rendered accessibility tree, and writes PNGs into [screenshots](../../docs/screenshots/). Non-default dimensions are added to filenames. It enters a harmless example sentence; if Groq is enabled this can exercise conversion. It also assumes the current onboarding path and a selectable saved voice, so a different live setup may need manual navigation or adaptation.

Captures are UI checks, not assertions of actual voice quality or a substitute for native playback/device testing. Do not capture entered keys or private recordings. Shut down temporary preview processes when finished.
