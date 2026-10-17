# Local backend

[Project handbook](../README.md)

This folder is the local FastAPI server. It sits between the Flet app and Colab/Groq, validates requests, prepares text/audio, and stores encrypted user data. The normal backend is CPU-only; XTTS runs in Colab.

## Contents

| File/folder | Responsibility |
| --- | --- |
| [app](app/README.md) | Importable server package, startup, settings, routes, services, and database. |
| [data](data/README.md) | Bundled phrase/dictionary resources and ignored default runtime locations. |
| [scripts](scripts/README.md) | Configuration, reference conversion, evaluation, benchmarks, optional model preparation. |
| [tests](tests/README.md) | Backend behavior and regression tests. |
| [.env.example](.env.example) | Complete settings template with defaults and explanations. |
| [requirements.txt](requirements.txt) | Normal runtime packages. |
| [requirements-safety.txt](requirements-safety.txt) | Optional local verification/watermark dependencies. |
| [requirements-eval.txt](requirements-eval.txt) | Optional quality-evaluation dependencies. |
| [.gitignore](.gitignore) | Excludes runtime databases, keys/model folders, environments, and reports. |

## Start it

For everyday Windows use, launch [Start ARIA.bat](../Start%20ARIA.bat). For a developer terminal, begin at the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements.txt
Set-Location aria_backend
..\.venv\Scripts\python.exe -m app
```

Default address: `http://127.0.0.1:8001`. Run one worker; in-memory sessions, locks, and admission budgets are not shared across multiple workers. The launcher creates protected settings, whereas bare defaults permit easier local development. See [configuration](../README.md#chapter-10--settings-and-keys) before changing network exposure.

## Request flow

1. Request guards apply authentication, origin, size, time, and admission limits.
2. An [API handler](app/api/README.md) validates fields and coordinates work.
3. [Services](app/services/README.md) prepare text/audio, access encrypted state, and call external services as needed.
4. The handler returns JSON or WAV, with safe errors and no-store headers.

CPU audio preparation runs in worker threads. A shared data lock coordinates related state changes, while selected background/verification work releases it and rechecks state before committing results. The phrase warmer avoids saving stale results after edits/deletion.

## Configuration and storage

The selected environment file is explicit `ARIA_BACKEND_ENV_FILE`, otherwise private `ARIA/config/backend.env`, otherwise this folder's `.env`. Process environment values override that file. Encrypted runtime connections saved by the app are also restored during startup.

`DATA_DIR` determines runtime storage. The private helper normally chooses a location outside the repository; the raw class default is this folder's data directory. Preserve the SQLite database and matching Fernet key together. Never commit a real environment file, recording, database, or model weight.

The database stores voice representations and caches, not the XTTS weights. Registering a voice calls Colab; local storage does not mean that the full processing path stays on the computer.

## Verify and modify

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest aria_backend/tests -q
```

Change route schemas in API modules, business behavior in services, shared defaults in settings, and persisted structures in the database package. Update the matching tests and `.env.example` when adding settings. Keep real secrets and model quality claims out of test fixtures and documentation.
