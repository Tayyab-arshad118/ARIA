"""Optional Windows UI capture against an already-running, loopback-only Flet preview."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

from websockets.sync.client import connect


def capture():
    root = Path(__file__).resolve().parents[2]
    edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    profile = Path(tempfile.mkdtemp(prefix="aria-ui-capture-"))
    process = subprocess.Popen([str(edge), "--headless=new", "--no-first-run", "--disable-extensions",
        "--force-device-scale-factor=1", "--window-size=1280,1000", "--remote-debugging-port=0",
        "--user-data-dir=" + str(profile), "http://127.0.0.1:8550"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 30
        port_file = profile / "DevToolsActivePort"
        while not port_file.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        port = int(port_file.read_text().splitlines()[0])
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list"))
        target = next(p for p in pages if p.get("type") == "page" and "127.0.0.1:8550" in p["url"])
        with connect(target["webSocketDebuggerUrl"], max_size=16 * 1024 * 1024) as socket:
            serial = 0
            def command(method, params=None):
                nonlocal serial
                serial += 1
                socket.send(json.dumps({"id": serial, "method": method, "params": params or {}}))
                while True:
                    reply = json.loads(socket.recv(timeout=15))
                    if reply.get("id") == serial:
                        if "error" in reply:
                            raise RuntimeError("Browser command failed")
                        return reply.get("result", {})
            command("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
            while time.monotonic() < deadline:
                title = command("Runtime.evaluate", {"expression": "document.title"})["result"].get("value", "")
                if "A.R.I.A" in title:
                    break
                time.sleep(0.25)
            time.sleep(2)
            command("Runtime.evaluate", {"expression": "document.querySelector('flt-semantics-placeholder')?.click()"})
            time.sleep(1)
            def save(name):
                result = command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                output = root / "docs/screenshots" / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(base64.b64decode(result["data"]))
            save("compose-light.png")
            # Read the semantic target before dispatching a native pointer event.
            target = command("Runtime.evaluate", {"expression": "JSON.stringify((()=>{const e=document.querySelector('[aria-label=\"Switch appearance\"]');if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())"})
            point = json.loads(target["result"].get("value", "null"))
            if point:
                for kind in ("mousePressed", "mouseReleased"):
                    command("Input.dispatchMouseEvent", {"type": kind, **point, "button": "left", "clickCount": 1})
                time.sleep(0.5)
                save("compose-dark.png")
                for kind in ("mousePressed", "mouseReleased"):
                    command("Input.dispatchMouseEvent", {"type": kind, **point, "button": "left", "clickCount": 1})
            command("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 1000, "deviceScaleFactor": 1, "mobile": True})
            time.sleep(1)
            save("compose-mobile.png")
            # Close only this fresh profile/browser, never an existing user browser.
            command("Browser.close")
            print("Captured desktop preview.")
    finally:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    capture()
