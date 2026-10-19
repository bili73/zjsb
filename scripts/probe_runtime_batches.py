"""Isolated Windows real-GPU/HTTP comparison; requires the live GPU owner stopped.

All business fixtures, credentials and keys are isolated. No Mac connection,
production task write, original-file edit or automatic production restart.
"""
from collections import Counter, defaultdict
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import http.cookiejar
import io
import json
import math
import msvcrt
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from ocr_app.storage import Storage


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def originals():
    """Read only frozen material/result fixtures; never log their values/names."""
    store=Storage(ROOT/'.runtime/data')
    fixtures=[];medical=[];seen=set()
    with closing(sqlite3.connect((ROOT/'.runtime/data/tasks.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        for kind in ['MEDICAL_REPORT','DIPLOMA']:
            rows=db.execute('SELECT * FROM tasks WHERE doc_type=? AND result_enc IS NOT NULL ORDER BY created_at DESC',(kind,)).fetchall()
            for row in rows:
                artifacts=db.execute("SELECT * FROM artifacts WHERE task_id=? AND run_id=? AND kind='corrected' ORDER BY page_index",(row['id'],row['run_id'])).fetchall()
                if not artifacts: continue
                meta=store.unpack(row['meta_enc']);data=store.read(row['input_ref'])
                fixture=dict(kind=kind,data=data,meta=meta,result=store.unpack(row['result_enc']),
                    pages=[dict(index=a['page_index'],width=a['width'],height=a['height'],data=store.read(a['reference'])) for a in artifacts])
                fixtures.append(fixture);break
        for row in db.execute("SELECT input_ref,meta_enc,content_hash FROM tasks WHERE doc_type='MEDICAL_REPORT' ORDER BY created_at DESC"):
            if row['content_hash'] in seen: continue
            seen.add(row['content_hash']);data=store.read(row['input_ref'])
            meta=store.unpack(row['meta_enc'])
            if data.startswith(b'%PDF') and meta.get('actual_source_page_count',0)>=20:
                medical.append(dict(id='medical-'+str(len(medical)+1),kind='MEDICAL_REPORT',data=data,
                    name='medical-'+str(len(medical)+1)+'.pdf',owner=len(medical)%3))
            if len(medical)==2: break
    assert len(fixtures)==2 and len(medical)==2,'Need two frozen read fixtures and two long real PDFs'
    return fixtures,medical


def picture(index,kind):
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(1000,760),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',30)
    if kind=='DIPLOMA':
        names=['测试甲','测试乙','测试丙','测试丁','测试戊','测试己','测试庚','测试辛','测试壬','测试癸','测试子','测试丑']
        lines=['毕业证书（合成测试）','姓名：'+names[index%len(names)],'学校：合成测试大学','专业：计算机科学与技术',
            '学历层次：本科','学制：四年','入学日期：2020年9月1日','毕业日期：2024年6月30日',
            '证书编号：12345202400000'+str(index).zfill(4)]
    elif kind=='TABLE':
        lines=['合成库存表 '+str(index),'项目        数量        单价','测试甲        12          18','测试乙        23          29','测试丙        34          37']
    else:
        lines=['合成登记资料 '+str(index),'申请人：测试甲','部门：测试部门','联系电话：13800138000','用途：批处理测试','申请日期：2026年10月19日']
    for y,line in enumerate(lines):draw.text((40,35+y*66),line,font=font,fill='black')
    target=io.BytesIO();image.save(target,format='PNG');return target.getvalue()


class Http:
    def __init__(self,base,label,metrics):
        self.base,self.label,self.metrics=base,label,metrics
        self.jar=http.cookiejar.CookieJar();self.csrf=''
        self.client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(self.jar))
    def call(self,label,path,body=None,content_type='application/json',phase='control',expected=(200,201,202,204)):
        if isinstance(body,dict):body=json.dumps(body).encode()
        headers={'Origin':self.base}
        if body is not None:headers.update({'Content-Type':content_type,'X-CSRF-Token':self.csrf})
        start=time.perf_counter()
        try:response=self.client.open(urllib.request.Request(self.base+path,data=body,headers=headers),timeout=30)
        except urllib.error.HTTPError as error:response=error
        with response:
            data=response.read();status=response.status
            self.metrics.append(dict(label=label,actor=self.label,phase=phase,status=status,
                wall_ms=round((time.perf_counter()-start)*1000,3),bytes=len(data),
                db_wait_ms=response.headers.get('X-DB-Wait-Ms'),db_hold_ms=response.headers.get('X-DB-Hold-Ms')))
            assert status in expected,(label,status)
            return json.loads(data) if 'application/json' in response.headers.get('Content-Type','') else None
    def login(self,name,password):
        self.csrf=self.call('login','/api/v1/auth/login',dict(username=name,password=password))['csrf_token']
    def upload(self,cases):
        boundary='runtime-batch-'+secrets.token_hex(8);parts=[]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="doc_type_hint"\r\n\r\n{cases[0]["kind"]}\r\n'.encode())
        for case in cases:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{case["name"]}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+case['data']+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        return self.call('upload','/api/v1/batches',b''.join(parts),'multipart/form-data; boundary='+boundary)


def seed_reads(business,fixtures,actor):
    seeded=[]
    for fixture in fixtures:
        meta=fixture['meta']
        created=business.store.create_batch([dict(data=fixture['data'],name='read-fixture',
            mime=meta['mime_type'],
            actual_source_page_count=meta.get('actual_source_page_count',1))],fixture['kind'],actor)
        task=business.store.claim_next([fixture['kind']])
        assert task['id']==created['task_ids'][0]
        for page in fixture['pages']:business.store.save_page(task,page['index'],page['data'],page['width'],page['height'])
        business.store.publish(task,fixture['result'])
        seeded.append(business.store.task(task['id']))
    return seeded


def loading_routes(fixtures):
    medical=next(t for t in fixtures if t['doc_type']=='MEDICAL_REPORT')
    diploma=next(t for t in fixtures if t['doc_type']=='DIPLOMA')
    def preview(t):return f'/api/v1/tasks/{t["task_id"]}/preview?run_id={t["run_id"]}&result_revision={t["result_revision"]}&page=1'
    return [('me','/api/v1/auth/me'),('batches','/api/v1/batches?page=1&page_size=50'),
        ('result','/api/v1/tasks/'+medical['task_id']+'/result'),('medical_preview',preview(medical)),
        ('diploma_preview',preview(diploma)),('diagnostic_status','/api/v1/admin/diagnostics/status'),
        ('diagnostic_events','/api/v1/admin/diagnostics/events?limit=50'),('static','/')]


def case_summary(business,case,task):
    from ocr_app.task_errors import TaskError
    try:
        result=business.store.result(task['task_id'],items_filter='all')
    except TaskError as error:
        if error.code!='INVALID_STATE' or task['status'] not in {'CANCELLED','FAILED','REJECTED'}:
            raise
        result={}
    fields=[dict(key=f['key'],value=f.get('value')) for f in result.get('fields',[])]
    with business.engine.connect() as connection:
        from sqlalchemy import text
        rows=connection.execute(text('SELECT payload_enc FROM attempts WHERE task_id=:task AND run_id=:run ORDER BY created_at,id'),
            dict(task=task['task_id'],run=task['run_id'])).scalars().all()
    attempts=[business.storage.unpack(value) for value in rows]
    norm=lambda value:' '.join(str(value).split())
    predictions=[dict(model=a.get('model'),task=a.get('task'),text=norm((a.get('prediction') or {}).get('text','')),
        stop=(a.get('prediction') or {}).get('termination_reason'),
        batch=(a.get('prediction') or {}).get('batch_size',1)) for a in attempts]
    fingerprint=lambda value:hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return dict(id=case['id'],kind=case['kind'],owner=case['owner'],status=task['status'],
        active_started_at=task.get('active_started_at'),updated_at=task.get('updated_at'),
        progress=task.get('progress_detail'),error=(task.get('error') or {}).get('code'),
        fields_hash=fingerprint(fields),ocr_hash=fingerprint([{k:v for k,v in a.items() if k!='batch'} for a in predictions]),
        attempts=len(attempts),batch_sizes=dict(Counter(a['batch'] for a in predictions)),
        stops=dict(Counter(a['stop'] for a in predictions)),input_sha256=hashlib.sha256(case['data']).hexdigest())


def cohort(business,runtime,clients,cases,label,metrics,routes,out,*,cancel=False):
    start=time.monotonic();tasks={};case_results=[];stop=threading.Event();sampling_errors=[]
    def sampling():
        try:
            while not stop.is_set():
                for name,path in routes:
                    if stop.is_set():return
                    clients[0].call(name,path,phase='during-'+label)
                stop.wait(.5)
        except Exception as error:sampling_errors.append(type(error).__name__)
    sampler=threading.Thread(target=sampling,daemon=True);sampler.start()
    try:
        groups=defaultdict(list)
        for case in cases:groups[(case['owner'],case['kind'])].append(case)
        def upload(group):
            (owner,kind),values=group
            created=clients[owner].upload(values)
            assert len(created['task_ids'])==len(values)
            return [(task_id,case) for task_id,case in zip(created['task_ids'],values)]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for group in pool.map(upload,groups.items()):tasks.update(group)
        terminal=set();cancelled=None;cancel_evidence=None;next_print=0
        while len(terminal)<len(tasks) and time.monotonic()-start<600:
            if cancel and cancelled is None:
                stats=runtime.request('statistics',wait=10)
                active=stats.get('active_requests',{}).get('glm_ocr',[])
                if len(active)==2 and all(row['task_id'] in tasks for row in active):
                    candidate=active[0]['task_id'];target=clients[0].call('cancel_snapshot','/api/v1/tasks/'+candidate)
                    if target['status'] in {'PREPROCESSING','OCR','EXTRACTING','VALIDATING'}:
                        owner=tasks[candidate]['owner']
                        response=clients[owner].call('cancel','/api/v1/tasks/'+candidate+'/cancel',
                            dict(run_id=target['run_id'],expected_revision=target['result_revision']),expected=(202,409))
                        if response.get('task_id')==candidate:
                            cancelled=candidate
                            cancel_evidence=dict(target_case=tasks[cancelled]['id'],peer_case=tasks[active[1]['task_id']]['id'],
                                model_pids_before=stats['model_pids'])
            for task_id,case in tasks.items():
                if task_id in terminal:continue
                task=clients[case['owner']].call('poll','/api/v1/tasks/'+task_id)
                assert task['task_id']==task_id
                if task['status'] in {'NEED_REVIEW','COMPLETED','FAILED','CANCELLED','REJECTED'}:
                    terminal.add(task_id)
                    value=case_summary(business,case,task)
                    value['complete_seconds']=round(time.monotonic()-start,3);case_results.append(value)
                    save(out/(label+'-partial.json'),dict(cases=case_results))
            if time.monotonic()>=next_print:
                print(json.dumps(dict(event='cohort_progress',label=label,done=len(terminal),total=len(tasks),
                    elapsed=round(time.monotonic()-start,1))),flush=True)
                next_print=time.monotonic()+15
            if len(terminal)<len(tasks):time.sleep(.25)
        assert len(terminal)==len(tasks),'Cohort deadline exceeded'
        if cancel:
            assert cancelled is not None,'No actual two-row batch observed for cancellation'
            current=runtime.request('statistics',wait=10)
            cancel_evidence['model_pids_after']=current['model_pids']
            cancel_evidence['models_ready']=current['runtime']['state']=='ready'
            assert cancel_evidence['model_pids_before']==cancel_evidence['model_pids_after']
            assert next(r for r in case_results if r['id']==cancel_evidence['target_case'])['status']=='CANCELLED'
            assert next(r for r in case_results if r['id']==cancel_evidence['peer_case'])['status'] in {'NEED_REVIEW','COMPLETED'}
        # Operator C cannot read another operator's B task/result.
        foreign=next((task_id for task_id,case in tasks.items() if case['owner']==1),None)
        if foreign:
            clients[2].call('ownership','/api/v1/tasks/'+foreign,expected=(403,404))
            clients[2].call('ownership_result','/api/v1/tasks/'+foreign+'/result',expected=(403,404))
        return dict(label=label,started_monotonic=start,finished_monotonic=time.monotonic(),
                    wall_seconds=round(time.monotonic()-start,3),cases=case_results,
                    cancel=cancel_evidence,sampling_errors=sampling_errors)
    finally:
        stop.set();sampler.join(35)


def run_round(out,size,fixtures,medical,include_medical=True):
    import uvicorn
    from ocr_app.api import create_app
    from ocr_app.business import Business
    from ocr_app.client import RuntimeClient
    from ocr_app.config import RuntimeConfig
    from ocr_app.diagnostics import init_diagnostics
    folder=out/('size'+str(size));folder.mkdir();private=out/'private'/('size'+str(size));private.mkdir()
    diagnostic=init_diagnostics(folder/'diagnostics','api')
    os.environ['OCR_DIAGNOSTICS_ROOT']=str(diagnostic.root);os.environ['OCR_DIAGNOSTICS_SESSION']=diagnostic.session_id
    business=Business(private/'data',diagnostic);business.prepare()
    password=secrets.token_urlsafe(24);accounts=[]
    for index in range(3):accounts.append(business.accounts.set_user('batch-test-'+str(index),password,'测试账号'+str(index),'operator'))
    accounts.sort(key=lambda a:a['user_id'])
    business.accounts.set_user(accounts[0]['username'],password,accounts[0]['display_name'],'admin')
    read_fixtures=seed_reads(business,fixtures,accounts[0]['user_id'])
    runtime=RuntimeClient(RuntimeConfig(folder/'session',data_root=business.root,model_batch_size=size))
    app=create_app(runtime,ROOT/'frontend/dist',folder/'session',business,diagnostic)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='warning'))
    thread=threading.Thread(target=server.run,kwargs=dict(sockets=[sock]),daemon=True);thread.start()
    metrics=[];clients=[Http('http://127.0.0.1:'+str(port),'ABC'[i],metrics) for i in range(3)]
    value=dict(batch_size=size,cohorts=[])
    try:
        until=time.monotonic()+20
        while not server.started and time.monotonic()<until:time.sleep(.1)
        assert server.started
        for index,client in enumerate(clients):client.login(accounts[index]['username'],password)
        password=None
        until=time.monotonic()+360
        while time.monotonic()<until:
            health=clients[0].call('health','/api/v1/health')
            if health['runtime']['state']=='ready':break
            time.sleep(1)
        else:raise RuntimeError('MODELS_NOT_READY')
        routes=loading_routes(read_fixtures)
        for _ in range(2):
            for label,path in routes:clients[0].call(label,path,phase='warmup')
        for _ in range(5):
            for label,path in routes:clients[0].call(label,path,phase='idle')
        cases=[]
        index=0
        for owner,count in enumerate([4,3,2]):
            for _ in range(count):
                cases.append(dict(id='certificate-'+str(index),kind='DIPLOMA',data=picture(index,'DIPLOMA'),name='certificate-'+str(index)+'.png',owner=owner));index+=1
        value['cohorts'].append(cohort(business,runtime,clients,cases,'certificates',metrics,routes,folder))
        paddle=[dict(id=kind.lower()+'-'+str(i),kind=kind,data=picture(i,kind),name=kind.lower()+'-'+str(i)+'.png',owner=i%3)
                for kind in ['GENERIC','TABLE'] for i in range(3)]
        value['cohorts'].append(cohort(business,runtime,clients,paddle,'forms-tables',metrics,routes,folder))
        mixed=[dict(id='mixed-'+kind.lower()+'-'+str(i),kind=kind,data=picture(20+i,kind),
                    name='mixed-'+kind.lower()+'-'+str(i)+'.png',owner=i)
               for i in range(3) for kind in ['DIPLOMA','GENERIC']]
        value['cohorts'].append(cohort(business,runtime,clients,mixed,'mixed-models',metrics,routes,folder))
        if include_medical:
            value['cohorts'].append(cohort(business,runtime,clients,medical,'medical',metrics,routes,folder))
        if size==2:
            cases=[dict(id='cancel-'+str(i),kind='DIPLOMA',data=picture(9+i,'DIPLOMA'),name='cancel-'+str(i)+'.png',owner=i%3) for i in range(6)]
            value['cohorts'].append(cohort(business,runtime,clients,cases,'cancel',metrics,routes,folder,cancel=True))
        value['statistics']=runtime.request('statistics',wait=10)
        value['health']=clients[0].call('final_health','/api/v1/health')
        assert value['health']['runtime']['state']=='ready'
    finally:
        if runtime.is_alive() and runtime.snapshot()['state']!='starting':
            try:value['statistics']=runtime.request('statistics',wait=10)
            except Exception as error:value['statistics_error']=type(error).__name__
        for client in clients:
            if client.csrf:
                try:client.call('logout','/api/v1/auth/logout',{})
                except Exception:pass
        server.should_exit=True;thread.join(30)
        if thread.is_alive():runtime.close(graceful=False);thread.join(5)
        diagnostic.close()
        save(folder/'report.json',{**value,'metrics':metrics})
    assert not thread.is_alive()
    return {**value,'metrics':metrics}


def percentile(values,p=.95):
    return sorted(values)[max(0,math.ceil(len(values)*p)-1)]


def compare(rounds,out):
    original={case['id']:case for cohort in rounds[0]['cohorts'] for case in cohort['cases']}
    trial={case['id']:case for cohort in rounds[1]['cohorts'] if cohort['label']!='cancel' for case in cohort['cases']}
    consistency=[]
    for identity,a in original.items():
        b=trial[identity];assert a['input_sha256']==b['input_sha256']
        consistency.append(dict(id=identity,fields_equal=a['fields_hash']==b['fields_hash'],ocr_equal=a['ocr_hash']==b['ocr_hash'],
            status1=a['status'],status2=b['status'],incomplete1=(a.get('progress') or {}).get('incomplete_regions'),
            incomplete2=(b.get('progress') or {}).get('incomplete_regions')))
    loading=[]
    for label in ['me','batches','result','medical_preview','diploma_preview','diagnostic_status','diagnostic_events','static']:
        values=[]
        for round in rounds:
            sample=[m['wall_ms'] for m in round['metrics'] if m['label']==label and m['phase'].startswith('during-')
                    and m['phase']!='during-cancel' and m['status']==200]
            values.append(dict(count=len(sample),median_ms=percentile(sample,.5),p95_ms=percentile(sample)))
        limit=max(values[0]['p95_ms']*1.5,values[0]['p95_ms']+200)
        loading.append(dict(label=label,size1=values[0],size2=values[1],limit_ms=limit,passed=values[1]['p95_ms']<=limit))
    errors=[m for round in rounds for m in round['metrics'] if m['status']>=500]
    batches=[m for m in rounds[1]['statistics']['metrics'] if m.get('operation')=='recognize_batch' and m.get('batch_size')==2]
    overlaps=[dict(left=a['inference_batch_id'],right=b['inference_batch_id']) for a in batches for b in batches
              if a['model']=='glm_ocr' and b['model']=='paddleocr_vl'
              and max(a['started_monotonic'],b['started_monotonic'])<min(a['finished_monotonic'],b['finished_monotonic'])]
    statuses=all(row['status2'] in {'NEED_REVIEW','COMPLETED'} for row in consistency)
    fields_unchanged=all(row['fields_equal'] for row in consistency)
    coverage=all((row['incomplete2'] or 0)<=(row['incomplete1'] or 0) for row in consistency)
    result=dict(scope='Windows isolated real-GPU production concurrency probe; not serial accuracy or Mac qualification',
        consistency=consistency,loading=loading,http_5xx=errors,actual_two_row_calls=len(batches),
        models_with_two_row_calls=sorted({row['model'] for row in batches}),
        cross_model_two_row_overlaps=overlaps,
        passed=statuses and fields_unchanged and coverage and not errors and not any(c['sampling_errors'] for r in rounds for c in r['cohorts'])
            and all(row['passed'] for row in loading)
            and {row['model'] for row in batches}=={'glm_ocr','paddleocr_vl'})
    save(out/'comparison.json',result);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--skip-medical',action='store_true',help='Short-material qualification only; does not qualify medical concurrency')
    args=parser.parse_args();out=args.output.resolve()
    assert out.is_relative_to(ROOT/'output')
    out.mkdir(exist_ok=False)
    (out/'private').mkdir()
    import subprocess
    identity=subprocess.check_output(['whoami'],text=True).strip()
    subprocess.run(['icacls',str(out/'private'),'/inheritance:r','/grant:r',identity+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],check=True,capture_output=True)
    save(out/'protocol.json',dict(max_batch=2,document_slots=3,immediate_singleton=True,
        medical_concurrency_tested=not args.skip_medical,http_clock='perf_counter',
        loading_limit='size2 active P95 <= max(1.5 * size1 active P95, size1 active P95 + 200ms)',
        privacy='separate DPAPI keys/accounts/storage; no plaintext results persisted',mac_operations=0))
    save(out/'code-hashes.json',{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        for path in [ROOT/'backend/model_worker.py',ROOT/'backend/ocr_app/runtime.py',ROOT/'backend/ocr_app/model_queues.py',
                     ROOT/'backend/ocr_app/batch_generation.py',ROOT/'backend/ocr_app/task_scheduler.py',Path(__file__)]})
    with (ROOT/'output/two-model-retest-gpu.lock').open('a+b') as lease:
        lease.seek(0);msvcrt.locking(lease.fileno(),msvcrt.LK_NBLCK,1)
        fixtures,medical=originals()
        rounds=[]
        for size in [1,2]:
            print(json.dumps(dict(event='round_start',batch_size=size)),flush=True)
            rounds.append(run_round(out,size,fixtures,medical,include_medical=not args.skip_medical))
            print(json.dumps(dict(event='round_end',batch_size=size)),flush=True)
        result=compare(rounds,out)
        print(json.dumps(dict(event='comparison',passed=result['passed'],two_row_calls=result['actual_two_row_calls'])),flush=True)
    return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
