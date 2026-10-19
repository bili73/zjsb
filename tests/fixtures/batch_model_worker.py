"""Synthetic JSON-lines child for real Windows Job and row-control tests."""
from pathlib import Path
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from ocr_app.model_protocol import ModelInbox

inbox = ModelInbox(sys.stdin)
while (item := inbox.messages.get()) is not None:
    request, controls = item
    identity = request.get('id')
    if request.get('op') == 'load':
        print(json.dumps(dict(id=identity,ok=True,result=dict(revision='cpu-batch'))),flush=True)
        continue
    done = set()
    began = time.monotonic()
    while len(done) < len(request['rows']):
        for row in request['rows']:
            name = row['row_id']
            if name in done:
                continue
            if controls[name].is_set():
                value = dict(ok=False,error_code='CANCELLED')
            elif time.monotonic() >= row['deadline']:
                value = dict(ok=False,error_code='EXTRACT_TIMEOUT')
            elif time.monotonic()-began >= (.5 if row['image']=='slow' else .05):
                value = dict(ok=True,result=dict(text=row['image'],termination_reason='eos',batch_size=len(request['rows'])))
            else:
                continue
            print(json.dumps(dict(id=identity,event='row_result',row_id=name,**value)),flush=True)
            done.add(name)
        time.sleep(.002)
    print(json.dumps(dict(id=identity,ok=True,result=dict(completed=len(done)))),flush=True)
    inbox.finish(identity)
