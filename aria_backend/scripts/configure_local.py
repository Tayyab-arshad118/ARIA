"""Create private desktop/backend settings without putting credentials into project files."""
import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys

from dotenv import dotenv_values, set_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, private_config_dir


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-prompt", action="store_true", help="Initialize secure local settings without asking for a Groq key")
    args = parser.parse_args()
    directory = private_config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    backend, desktop = directory / "backend.env", directory / "desktop.env"
    existing = dotenv_values(backend)
    key = "" if args.no_prompt else getpass.getpass("Groq API key (hidden; Enter keeps the existing key): ").strip()
    key = key or existing.get("GROQ_API_KEY", "")
    token = existing.get("ARIA_KEY") or secrets.token_urlsafe(48)
    if len(token) < 32:
        token = secrets.token_urlsafe(48)
    data_dir = existing.get("DATA_DIR") or str(ROOT / "data" if (ROOT / "data/aria.sqlite").exists() else directory.parent / "data")
    fields = {"ARIA_KEY": token, "REQUIRE_AUTH": "true", "HOST": "127.0.0.1", "PORT": "8001",
        "DOCS_ENABLED": "false", "ALLOWED_HOSTS": '["localhost","127.0.0.1","[::1]"]',
        "ALLOWED_ORIGINS": "[]", "DATA_DIR": data_dir}
    if key:
        fields.update(GROQ_API_KEY=key, LLM_TRANSLIT_ENABLED="true", LOCAL_ONLY="false", TRANSLIT_STRATEGY="api_first")
    for name, value in fields.items():
        set_key(str(backend), name, value)
    set_key(str(desktop), "ARIA_KEY", token)
    set_key(str(desktop), "ARIA_BACKEND_URL", "http://127.0.0.1:8001")
    if os.name == "nt":
        account = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(["icacls", str(directory.parent), "/inheritance:r", "/grant:r",
            f"{account}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], check=True, stdout=subprocess.DEVNULL)
    else:
        directory.chmod(0o700)
        for path in (backend, desktop):
            path.chmod(0o600)
    print("Private configuration is ready. Restart the backend and desktop app.")
    print("An existing project database is not moved automatically; keep DATA_DIR pointing to it if needed.")


if __name__ == "__main__":
    main()
