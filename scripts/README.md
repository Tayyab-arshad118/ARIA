# Startup scripts

[Project handbook](../README.md)

These files make the Windows desktop workflow a single launch action. They do not start a Google Colab runtime or download the user's voice model.

## Startup chain

```text
Start ARIA.bat
    → start_aria.ps1
        → launch_aria.py
            → local backend, if needed
            → native Flet desktop app
```

| File | Responsibility |
| --- | --- |
| [Start ARIA.bat](../Start%20ARIA.bat) | Calls PowerShell relative to its own location and keeps an error visible when startup fails. |
| [start_aria.ps1](start_aria.ps1) | Finds the project, creates `.venv`, checks dependency hashes, installs changed requirements, calls the Python launcher. |
| [launch_aria.py](launch_aria.py) | Initializes missing protected settings, validates the shared local connection, manages the lock/backend/app lifecycle. |

## Process ownership

The Python launcher probes the local backend using the configured key. If it must start one, it waits for readiness before opening the app. A busy port used by an incompatible service is reported rather than forcibly cleared.

Closing the app stops the backend that this launcher started, including its Windows child process tree. An already-running backend that was reused is left alone. The Windows launcher lock prevents duplicate app instances; it is runtime data, not a source file.

## First-run settings

When both standard private files are not present and no explicit environment-file override is supplied, the launcher invokes [configure_local.py](../aria_backend/scripts/configure_local.py) without an interactive Groq prompt. The user can add the Groq key through Connect later.

Custom environment files must still point the app and backend at matching local credentials/address. This launcher expects the local installation it manages; use manual startup for a deliberately different deployment.

## Diagnostics

From the project root:

```powershell
.\.venv\Scripts\python.exe scripts/launch_aria.py --check
```

This checks installation/settings without opening processes. The backend startup log is `startup.log` under active `DATA_DIR`. Dependency stamps live under `.venv` and should not be committed. First-run installation needs internet and Python 3.12; later runs reuse the environment.

Keep shell paths quoted and secrets out of command arguments. Changes to process cleanup should only target processes created by the launcher, never all Python instances on a machine.
