# Backend application package

[Project handbook](../../README.md) · [Backend folder](../README.md)

This is the Python package started by `python -m app` from the backend directory. It connects the HTTP layer to shared services and persistent data.

## Files and subpackages

| Item | What it does |
| --- | --- |
| [__init__.py](__init__.py) | Marks this directory as a Python package. |
| [__main__.py](__main__.py) | Starts Uvicorn with configured host/port, one worker, and access logging disabled. |
| [main.py](main.py) | Builds FastAPI, registers middleware/routers, and creates/closes shared services. |
| [config.py](config.py) | Validates settings, selects the environment file, and checks Colab origins. |
| [cli.py](cli.py) | Updates a running backend's Colab URL and optional key. |
| [api](api/README.md) | HTTP request/response handlers. |
| [services](services/README.md) | Text, audio, caching, external clients, and safety logic. |
| [db](db/README.md) | SQLAlchemy models and database sessions. |

## Startup and shutdown

Startup opens the database and encryption key, creates the GPU client, restores saved connection/language state, creates text/voice/cache/safety services, seeds phrases once, rebuilds prediction, and starts phrase warming if enabled. These instances live on `app.state` so requests share the same configuration and state.

Shutdown stops background warming, revokes in-memory verification state, closes HTTP clients, and disposes database resources. Do not start duplicate workers expecting shared in-memory state.

## Settings details

`Settings()` reads the explicit/private/project environment file and process environment. Defaults are relative to the backend folder where appropriate, not the shell's current directory. Runtime Colab/Groq settings can subsequently override integration values loaded from files. Secrets use masked settings types; do not log model dumps or whole environment files.

Validation catches unsafe/non-loopback binding without a strong key, incompatible reference limits, invalid model metadata, and malformed server URLs. The example configuration is in [the parent folder](../.env.example).

## Data lock and request guards

The shared data lock prevents conflicting voice/phrase/cache operations from racing. Long-running work sometimes takes a snapshot, releases the lock, and verifies the snapshot before saving. Middleware separately bounds body bytes/deadlines and concurrent requests. These solve different problems and should not be replaced with one unlimited global queue.

## Administration command

From the backend folder:

```powershell
..\.venv\Scripts\python.exe -m app.cli set-colab-url https://YOUR-TUNNEL.trycloudflare.com --update-key
```

The optional key is read from settings, not passed in the command. This CLI uses the direct update route; use checked Connect in the app when you want the model endpoint probed before saving.
