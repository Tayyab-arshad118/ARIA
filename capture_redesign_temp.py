"""Capture the running Flet web preview at an actual 390x844 CSS viewport."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from websockets.sync.client import connect

root = Path(__file__).resolve().parent
profile = Path(tempfile.mkdtemp(prefix='aria-redesign-preview-'))
edge = Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
process = subprocess.Popen([str(edge), '--headless=new', '--no-first-run', '--disable-extensions',
    '--force-device-scale-factor=1', '--window-size=360,640', '--remote-debugging-port=0',
    '--user-data-dir='+str(profile), 'http://127.0.0.1:8550'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    port_file = profile/'DevToolsActivePort'
    deadline = time.monotonic()+35
    while not port_file.exists() and time.monotonic()<deadline:
        time.sleep(.1)
    port = int(port_file.read_text().splitlines()[0])
    pages = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list'))
    page = next(p for p in pages if p.get('type')=='page' and '8550' in p['url'])
    with connect(page['webSocketDebuggerUrl'], max_size=16*1024*1024) as socket:
        serial = 0
        def command(method, params=None):
            global serial
            serial += 1
            socket.send(json.dumps({'id':serial,'method':method,'params':params or {}}))
            while True:
                result=json.loads(socket.recv(timeout=20))
                if result.get('id')==serial:
                    if 'error' in result:
                        raise RuntimeError(result['error'])
                    return result.get('result',{})
        command('Emulation.setDeviceMetricsOverride', {'width':360,'height':640,'deviceScaleFactor':1,'mobile':False})
        for _ in range(90):
            command('Runtime.evaluate', {'expression':"document.querySelector('flt-semantics-placeholder')?.click()"})
            result=command('Runtime.evaluate', {'expression':"!![...document.querySelectorAll('[role=button]')].find(e=>e.textContent.trim()==='Get started')"})
            if result.get('result',{}).get('value'):
                break
            time.sleep(.3)
        else:
            raise RuntimeError('Welcome not ready')
        def save(name):
            time.sleep(.35)
            screenshot=command('Page.captureScreenshot',{'format':'png'})['data']
            (root/'docs/screenshots'/f'ui-redesign-{name}-360x640.png').write_bytes(base64.b64decode(screenshot))
        def click(label):
            expression="JSON.stringify((()=>{const e=[...document.querySelectorAll('[role=button]')].find(e=>e.textContent.trim()==="+json.dumps(label)+");if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())"
            value=command('Runtime.evaluate',{'expression':expression})['result'].get('value')
            if not value or value=='null':
                raise RuntimeError('Control not found: '+label)
            point=json.loads(value)
            for event in ('mousePressed','mouseReleased'):
                command('Input.dispatchMouseEvent',{'type':event,**point,'button':'left','clickCount':1})
            time.sleep(.55)
        save('welcome')
        click('Get started')
        save('language')
        click('Continue')
        save('account')
        click('Choose a voice')
        save('voices')
        click('Use ARIA Voice')
        save('ready')
        click('Start speaking')
        save('speak')
        click('Phrases')
        save('phrases')
        click('Profile')
        save('profile')
        print('Captured phone-sized setup and main screens')
finally:
    process.terminate()
    process.wait(timeout=10)
