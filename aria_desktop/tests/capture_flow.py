"""Capture the public onboarding flow at a stable phone viewport (local preview on port 8550)."""
import base64
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

from websockets.sync.client import connect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=390)
    parser.add_argument("--height", type=int, default=844)
    args = parser.parse_args()
    width, height = args.width, args.height
    root = Path(__file__).resolve().parents[2]
    profile = Path(tempfile.mkdtemp(prefix="aria-flow-capture-"))
    edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    process = subprocess.Popen([str(edge), "--headless=new", "--no-first-run", "--disable-extensions",
        "--force-device-scale-factor=1", f"--window-size={width},{height}", "--remote-debugging-port=0",
        "--user-data-dir=" + str(profile), "http://127.0.0.1:8550"], stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 30
        port_file = profile / "DevToolsActivePort"
        while not port_file.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        port = int(port_file.read_text().splitlines()[0])
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list"))
        target = next(p for p in pages if p.get("type") == "page" and "8550" in p["url"])
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
            command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
            for _ in range(100):
                command("Runtime.evaluate", {"expression": "document.querySelector('flt-semantics-placeholder')?.click()"})
                result = command("Runtime.evaluate", {"expression": "[...document.querySelectorAll('[role=button]')].some(e=>e.textContent.trim()==='Get started')"})
                if result.get("result", {}).get("value"):
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError("Welcome screen did not finish loading")
            time.sleep(0.5)
            def save(name):
                command("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"})
                time.sleep(0.2)
                if (width, height) != (390, 844):
                    name = name.replace(".png", f"-{width}x{height}.png")
                output = root / "docs/screenshots" / name
                data = command("Page.captureScreenshot", {"format": "png"})
                output.write_bytes(base64.b64decode(data["data"]))
            def click(label):
                # Use the rendered accessibility tree, never image coordinates.
                js = "JSON.stringify((()=>{const e=[...document.querySelectorAll('[role=button]')].find(e=>e.textContent.trim()===" + json.dumps(label) + ");if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())"
                result = command("Runtime.evaluate", {"expression": js})
                point = json.loads(result["result"].get("value", "null"))
                if not point:
                    js = "JSON.stringify((()=>{const e=[...document.querySelectorAll('[role=button]')].find(e=>(e.getAttribute('aria-label')||'').trim()===" + json.dumps(label) + ");if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())"
                    result = command("Runtime.evaluate", {"expression": js})
                    point = json.loads(result["result"].get("value", "null"))
                if not point:
                    js = "JSON.stringify((()=>{const e=[...document.querySelectorAll('[aria-label]')].find(e=>e.getAttribute('aria-label')===" + json.dumps(label) + ");if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())"
                    result = command("Runtime.evaluate", {"expression": js})
                    point = json.loads(result["result"].get("value", "null"))
                if not point:
                    raise RuntimeError("Screen control missing: " + label)
                for event in ("mousePressed", "mouseReleased"):
                    command("Input.dispatchMouseEvent", {"type": event, **point, "button": "left", "clickCount": 1})
                time.sleep(1)
            for _ in range(40):
                ready = command("Runtime.evaluate", {"expression": "[...document.querySelectorAll('[role=button]')].some(e=>e.textContent.trim()==='Get started' && e.getAttribute('aria-disabled')!=='true')"})
                if ready.get('result', {}).get('value'):
                    break
                time.sleep(.25)
            save("onboarding-welcome.png")
            click("Get started")
            save("onboarding-connect.png")
            # Scroll the Flet page if the offline button is below the phone viewport.
            command("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 300, "y": min(700, height - 120), "deltaX": 0, "deltaY": 420})
            time.sleep(0.4)
            click("Use saved voices offline")
            command("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 300, "y": 400, "deltaX": 0, "deltaY": -2000})
            time.sleep(0.4)
            save("onboarding-voices.png")
            click("Continue to speaking")
            command("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 300, "y": 400, "deltaX": 0, "deltaY": -2000})
            time.sleep(0.4)
            save("onboarding-compose.png")
            click("Phrases")
            time.sleep(1)
            save("quick-phrases-phone.png")
            click("Compose")
            click("English")
            # Exercise the actual preview UI with a harmless sample sentence.
            result = command("Runtime.evaluate", {"expression": "JSON.stringify((()=>{const e=document.querySelector('textarea,input[role=textbox]');if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())"})
            point = json.loads(result['result'].get('value', 'null'))
            if point:
                for event in ('mousePressed', 'mouseReleased'):
                    command('Input.dispatchMouseEvent', {'type': event, **point, 'button': 'left', 'clickCount': 1})
                command('Input.insertText', {'text': 'my name is tayyab'})
                time.sleep(3)
            save('speak-english-light.png')
            click('Switch appearance')
            save('speak-english-dark.png')
        print("Phone-sized welcome, connection and voice screen captures saved.")
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
