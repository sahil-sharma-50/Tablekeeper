from pathlib import Path
import hashlib
import json
import subprocess
import time
from urllib.request import urlopen, Request

clone = Path(r'C:\Users\sahil\AppData\Local\Temp\tablekeeper-submission-validation-1ac39237')
out = Path(r'C:\Users\sahil\AppData\Local\Temp\tablekeeper-validation-ec7d6c1-runbooks')
out.mkdir(exist_ok=False)
source = Path(r'C:\Users\sahil\Desktop\BAND - Dark Factory\tablekeeper-v4')
assert hashlib.sha256((clone/'room.json').read_bytes()).digest() == hashlib.sha256((source/'room.json').read_bytes()).digest()
summary=[]
for stage, port in [(1,8102),(2,8102),(3,8103),(4,8104)]:
    tag=f'tablekeeper-stage-{stage}'
    name=f'tablekeeper-runbook-stage-{stage}'
    work=clone/f'stage-{stage}'
    log=out/f'stage-{stage}-build.log'
    with log.open('w',encoding='utf-8') as f:
        subprocess.run(['docker','build','-t',tag,'.'],cwd=work,stdout=f,stderr=subprocess.STDOUT,check=True)
    subprocess.run(['docker','run','--rm','-d','--name',name,'-p',f'127.0.0.1:{port}:{port}','-e',f'PORT={port}',tag],capture_output=True,check=True)
    try:
        start=time.monotonic()
        while True:
            try:
                with urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:
                    assert json.load(response)=={'status':'ok'}
                break
            except Exception:
                if time.monotonic()-start>60:
                    raise
                time.sleep(.25)
        paths=['/health']
        if stage>=2:
            paths+=['/','/login','/signup','/lookup','/assets/source-sans-3.woff2','/assets/restaurant-illustration.png','/assets/signin-bistro.png','/assets/signup-table.png']
        for path in paths:
            with urlopen(f'http://127.0.0.1:{port}{path}',timeout=5) as response:
                assert response.status==200 and response.read(), path
        if stage>=2:
            fixture=(work/'demo/multi-day-demo.json').read_bytes()
            with urlopen(Request(f'http://127.0.0.1:{port}/_test/reset',data=fixture,headers={'Content-Type':'application/json'},method='POST'),timeout=10) as response:
                assert response.status==204
            with urlopen(f'http://127.0.0.1:{port}/restaurants',timeout=5) as response:
                assert json.load(response)['restaurants']
        item={'stage':stage,'port':port,'build':'pass','health':'pass','routes_assets':len(paths),'demo_reset':'pass' if stage>=2 else 'not applicable'}
        summary.append(item)
        print(json.dumps(item),flush=True)
    finally:
        subprocess.run(['docker','stop',name],capture_output=True,check=True)
(out/'summary.json').write_text(json.dumps({'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=clone,text=True).strip(),'runbooks':summary},indent=2),encoding='utf-8')
print('All four RUN.md build/runtime settings verified; validation containers stopped.',flush=True)
