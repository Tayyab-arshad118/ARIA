# A.R.I.A

**Artificial Restoration of Individuals' Audio**

A.R.I.A. is a multilingual voice application for converting Roman Urdu or native-script
text into speech with an enrolled voice. The project combines a Flet desktop client, a
local FastAPI backend, and an optional Colab GPU inference server running an XTTS
checkpoint.

> **Status:** The application, backend, quick phrases, prediction, and optional safety
> features are implemented. Real XTTS checkpoint inference, voice quality, and Android
> packaging still require environment-specific acceptance testing.

## Features

- Roman Urdu to Urdu-script transliteration using a local dictionary and rules.
- Optional Groq-assisted transliteration with encrypted caching and local fallback.
- Voice enrollment from WAV, MP3, M4A, AAC, OGG, or FLAC files.
- Long-text chunking, speed control, audio caching, and in-memory playback.
- Quick phrases with language selection, search, favorites, recents, and prepared audio.
- Local next-word prediction for Roman Urdu input.
- Light/dark responsive Flet UI with bundled Nastaliq font support.
- Optional AudioSeal watermarking, challenge-response verification, and emotion references.
- Bounded requests, optional bearer authentication, host/origin checks, and encrypted
  local voice and cache data.

## Architecture

```text
Flet desktop app
        |
        v
Local FastAPI backend ---- SQLite + encrypted voice/audio/text data
        |
        v
Colab GPU server ---- XTTS model and cloudflared HTTPS tunnel
```

The desktop app communicates only with the local backend. The backend is responsible for
transliteration, validation, voice storage, caching, and communication with Colab.
Groq is optional and disabled by default. Model files, API keys, voice recordings, and
runtime databases are not included in this repository.

## Quick start on Windows

The simplest option is to double-click [Start ARIA.bat](Start%20ARIA.bat). The launcher:

1. Creates `.venv` with Python 3.12 if it does not exist.
2. Installs or updates the backend and desktop dependencies.
3. Starts the local backend and Flet desktop app together.

For actual voice synthesis, start the [Colab GPU notebook](colab/ARIA_Colab_GPU.ipynb)
first. The app's **Connect** screen accepts the Colab URL and API key; do not put the
Colab key or a Groq key into the desktop app.

The launcher is intended for Windows. For manual setup or Linux/macOS commands, see the
[backend guide](aria_backend/README.md) and [desktop guide](aria_desktop/README.md).

## Manual setup

From the repository root in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r aria_backend\requirements.txt
.\.venv\Scripts\python.exe -m pip install -r aria_desktop\requirements.txt
Copy-Item aria_backend\.env.example aria_backend\.env
Copy-Item aria_desktop\.env.example aria_desktop\.env
```

Edit the copied environment files before running. Keep secrets in local environment
files or the private configuration created by the setup helper; never commit them.

Start the backend:

```powershell
Set-Location aria_backend
..\.venv\Scripts\python.exe -m app
```

In a second terminal, start the desktop app from the project root:

```powershell
.\.venv\Scripts\python.exe aria_desktop\aria_app.py
```

The backend listens on `http://127.0.0.1:8001` by default. Set `ARIA_BACKEND_URL` in
`aria_desktop\.env` if the backend uses another address. Set `COLAB_URL` and
`COLAB_API_KEY` in `aria_backend\.env` after starting the notebook, or connect through
the app's onboarding flow.

## Colab GPU server

1. Upload [ARIA_Colab_GPU.ipynb](colab/ARIA_Colab_GPU.ipynb) to Google Colab.
2. Select a T4 GPU runtime and run the setup cells.
3. Set the model, config, vocabulary, and reference-audio paths in the notebook.
4. Run the server and copy the generated URL and one-time API key.
5. Paste those values into the app's **Connect** screen or the backend environment.

The notebook uses a quick Cloudflare tunnel, so the URL changes between sessions. Keep
the notebook running while using live synthesis. The supplied checkpoint and model
artifacts are intentionally not stored in Git.

## Repository layout

```text
proj/
├── aria_backend/       # FastAPI backend, services, database, data, and tests
├── aria_desktop/       # Flet desktop app, assets, configuration, and tests
├── colab/              # GPU inference notebook
├── flutter_ui/         # Early Flutter UI prototype
├── examples/           # Sample audio and conversion notes
├── docs/               # Additional setup documentation
├── scripts/            # Windows launcher helpers
├── tests/              # Notebook and integration tests
├── PHASE4.md           # Quick phrases and prediction
├── PHASE5.md           # Optional safety features
├── UI_AND_SECURITY.md  # UI, transliteration, and hardening notes
└── requirements-test.txt
```

## Configuration and privacy

- Copy `.env.example` files; do not edit or commit real credentials to source control.
- Keep `GROQ_API_KEY`, `COLAB_API_KEY`, and `ARIA_KEY` outside the repository.
- `LOCAL_ONLY=true` prevents third-party inference calls other than the configured Colab
  server. `LLM_TRANSLIT_ENABLED=false` disables Groq transliteration.
- `REQUIRE_AUTH=true` is recommended before exposing the backend beyond loopback.
- Raw recordings are not retained by default. Encrypted voice data and caches are stored
  in the backend runtime data directory.
- Cloudflare, Google Colab, and Groq may process data when those optional services are
  enabled. Review the detailed [security and UI notes](UI_AND_SECURITY.md) before using
  real voice recordings.

See [aria_backend/.env.example](aria_backend/.env.example) and
[aria_desktop/.env.example](aria_desktop/.env.example) for all supported settings.

## Testing

The test suite uses fake model and CUDA objects for local verification; it does not
download XTTS, access Google Drive, or measure speech quality.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Backend and desktop tests can also be run with their installed project dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest aria_backend\tests aria_desktop\tests -q
```

For detailed API contracts and troubleshooting, read the
[backend README](aria_backend/README.md), [desktop README](aria_desktop/README.md),
[Phase 4 guide](PHASE4.md), and [Phase 5 guide](PHASE5.md).
