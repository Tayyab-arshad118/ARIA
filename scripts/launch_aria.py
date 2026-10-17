"""Start the protected local server, wait until ready, then open the native phone-shaped app."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "aria_backend"), str(ROOT / "aria_desktop")]


def local_server_ready(url, token):
    import httpx
    try:
        response = httpx.get(url + "/api/voices", headers={"Authorization": "Bearer " + token},
                             timeout=2, trust_env=False, follow_redirects=False)
        return response.status_code == 200 and isinstance(response.json(), list)
    except (httpx.HTTPError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check installation and settings without starting processes")
    args = parser.parse_args()
    # Initialize before importing Settings, whose default env path is computed on import.
    private = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".config"))) / "ARIA/config"
    if not os.environ.get("ARIA_BACKEND_ENV_FILE") and not os.environ.get("ARIA_APP_ENV_FILE") and not all(
            (private / name).is_file() for name in ("backend.env", "desktop.env")):
        subprocess.run([sys.executable, str(ROOT / "aria_backend/scripts/configure_local.py"), "--no-prompt"], check=True)
    from app.config import Settings
    from aria_app import AppSettings
    backend, desktop = Settings(), AppSettings.from_env()
    origin = f"http://127.0.0.1:{backend.port}"
    if desktop.backend_url not in {origin, f"http://localhost:{backend.port}"} or desktop.api_key != backend.aria_key.get_secret_value():
        print("The desktop and local server settings do not match. Run the private configuration helper, or align your custom environment files.")
        return 1
    if args.check:
        print("ARIA installation and shared local connection settings are ready.")
        return 0
    backend.data_dir.mkdir(parents=True, exist_ok=True)
    lock = (backend.data_dir / "desktop-launcher.lock").open("a+b")
    if os.name == "nt":
        import msvcrt
        lock.seek(0)
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("ARIA is already running. Switch to its app window.")
            lock.close()
            return 0
    server = None
    log = None
    try:
        if not local_server_ready(origin, desktop.api_key):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", backend.port)) == 0:
                    print("The local server port is occupied by another service or an older ARIA instance. Close that instance and try again.")
                    return 1
            log = (backend.data_dir / "startup.log").open("a", encoding="utf-8")
            server = subprocess.Popen([sys.executable, "-m", "app"], cwd=ROOT / "aria_backend",
                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 45
            while not local_server_ready(origin, desktop.api_key):
                if server.poll() is not None or time.monotonic() >= deadline:
                    print("The local server could not start. See startup.log in your ARIA data folder.")
                    return 1
                time.sleep(0.25)
        print("ARIA is ready. Paste your two Colab outputs in Connect. Close the app to stop this launcher.")
        return subprocess.call([sys.executable, str(ROOT / "aria_desktop/aria_app.py")], cwd=ROOT)
    finally:
        if server is not None and server.poll() is None:
            if os.name == "nt":
                # A Windows venv executable can spawn a second Python process. Stop only
                # the process tree we started so the real server cannot remain on the port.
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if log:
            log.close()
        lock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print("ARIA could not start. Check Python, your environment settings, and access to the ARIA data folder.")
        raise SystemExit(1)
