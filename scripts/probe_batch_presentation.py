"""Only UTC+8, batch ordering and type-derived titles: isolated synthetic browser QA."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import secrets
import shutil
import socket
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from probe_review_browser import FakeRuntime

BROWSER=r'''
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const a=JSON.parse(fs.readFileSync(0,'utf8')),report={status:'failed',checks:[]};let browser,stage='start';
 try{
  browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const context=await browser.newContext({timezoneId:'UTC',viewport:{width:1440,height:1000}}),page=await context.newPage();page.setDefaultTimeout(20000);
  let errors=0;page.on('pageerror',()=>errors++);await page.goto(a.url);assert.equal(await page.evaluate(()=>Intl.DateTimeFormat().resolvedOptions().timeZone),'UTC');
  await page.getByPlaceholder('访问密钥',{exact:true}).fill(a.key);await page.getByRole('button',{name:'进入工作台'}).click();await page.getByRole('tab',{name:'任务批次'}).click();
  const rows=page.locator('.batch-collapse > .el-collapse-item');
  const verify=async(count)=>{
   await page.waitForFunction(n=>document.querySelectorAll('.batch-collapse > .el-collapse-item').length===n,count);
   const actual=await rows.evaluateAll(nodes=>nodes.map(n=>({name:n.querySelector('.batch-name').textContent.trim(),meta:n.querySelector('.batch-meta').textContent.trim()})));
   actual.forEach((row,i)=>{assert.equal(row.name,a.expected[i].label);assert.ok(row.meta.includes(a.expected[i].display));assert.ok(row.meta.includes('UTC+8'));assert.ok(!row.name.includes('上传批次'));});
   return actual;
  };
  stage='initial';await verify(50);await page.waitForFunction(()=>[...document.querySelectorAll('.batch-meta')].slice(0,50).every(n=>n.textContent.includes('执行中')));
  report.checks.push('UTC_browser_renders_explicit_UTC8_cross_midnight_and_creation_for_running_batches');
  stage='refresh';const refresh=page.waitForResponse(r=>r.url().includes('/api/v1/batches?page=1'));await page.getByRole('button',{name:'刷新',exact:true}).click();assert.equal((await refresh).status(),200);await verify(50);report.checks.push('first_50_descending_initial_and_refresh');
  stage='load_more';const more=page.waitForResponse(r=>r.url().includes('/api/v1/batches?page=2'));await page.getByRole('button',{name:'加载更早的批次'}).click();assert.equal((await more).status(),200);const all=await verify(52);assert.equal(await page.getByRole('button',{name:'加载更早的批次'}).count(),0);report.checks.push('real_page2_load_more_keeps_52_descending');
  stage='refresh_after_more';const again=page.waitForResponse(r=>r.url().includes('/api/v1/batches?page=1'));await page.getByRole('button',{name:'刷新',exact:true}).click();await again;await verify(52);report.checks.push('refresh_preserves_loaded_older_batches_order');
  stage='same_type_identity';for(const i of [0,3]){const row=rows.nth(i);await row.locator('.el-collapse-item__header').click();await row.getByText(a.expected[i].filename,{exact:true}).waitFor();assert.equal(await row.locator('.file-cell').count(),1);}
  const response=await context.request.get(a.url+'/api/v1/batches?page=1&page_size=100',{headers:{'X-API-Key':a.key}});assert.equal(response.status(),200);const batches=await response.json();assert.equal(new Set(batches.items.map(b=>b.batch_id)).size,52);assert.equal(batches.items[0].display_name,batches.items[3].display_name);assert.notEqual(batches.items[0].batch_id,batches.items[3].batch_id);assert.ok(batches.items.every((b,i)=>b.display_name===a.expected[i].label));report.checks.push('same_type_batches_keep_distinct_ids_tasks_and_backend_projected_titles');
  await page.getByRole('button',{name:'刷新',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:a.out+'/utc-browser-batches.png'});
  report.status='passed';report.browser_timezone='UTC';report.first_three=all.slice(0,3);report.last_two=all.slice(-2);report.batch_count=52;report.page_errors=errors;assert.equal(errors,0);
 }catch(e){report.status='failed';report.failure_stage=stage;report.failure_type=e.constructor.name;}
 finally{if(browser)await browser.close();report.browser_closed=true;process.stdout.write(JSON.stringify(report));}
})();
'''


def main():
    from PIL import Image
    from sqlalchemy import text
    from ocr_app.api import create_app
    from ocr_app.business import Business
    from ocr_app.doc_profiles import LABELS
    from ocr_app.winjob import JobProcess
    import uvicorn
    out=ROOT/'output/batch-presentation-browser-20261008-v1';out.mkdir(exist_ok=True)
    attempt=out/f'attempt-{len(list(out.glob("attempt-*")))+1:03}';attempt.mkdir()
    shutil.copytree(ROOT/'frontend/dist',attempt/'static')
    sources=[ROOT/name for name in ('frontend/src/presentation.ts','frontend/src/monitor.ts','frontend/src/components/BatchBoard.vue','backend/ocr_app/task_store.py','backend/ocr_app/routes.py')]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    business=Business(attempt/'private/data',key=secrets.token_bytes(32));business.accounts.accounts[0]['display_name']='合成批次展示验收'
    raw=io.BytesIO();Image.new('RGB',(16,12),'white').save(raw,format='PNG')
    expected=[];base=datetime(2026,10,8,15,40,tzinfo=timezone.utc)
    kinds=['DIPLOMA','DEGREE_CERT','MEDICAL_REPORT']
    # Permuted insertion order ensures presentation does not accidentally pass by insertion order.
    for offset in range(52):
        index=(offset*17)%52;kind=kinds[index%3];created=base+timedelta(minutes=index)
        filename=f'synthetic-{index:03}.png'
        batch=business.store.create_batch([dict(data=raw.getvalue(),name=filename,mime='image/png',actual_source_page_count=1)],kind,'synthetic')
        with business.store.transaction() as connection:
            connection.execute(text('UPDATE batches SET created_at=:at WHERE id=:id'),dict(at=created.isoformat(),id=batch['batch_id']))
        expected.append(dict(label=LABELS[kind],filename=filename,utc=created.isoformat(),display=(created+timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')))
    expected.sort(key=lambda row:row['utc'],reverse=True)
    runtime=FakeRuntime();app=create_app(runtime,attempt/'static',attempt/'private/session',business=business)
    sock=socket.socket();sock.bind(('127.0.0.1',0));url=f'http://127.0.0.1:{sock.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app,access_log=False,log_config=None,log_level='critical'));thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    report=dict(status='failed',scope='Only UTC+8/date rollover, descending batch pagination, type titles and distinct identities; synthetic DB, real HTTP, headless Edge in UTC')
    process=None
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.05)
        assert server.started
        process=JobProcess(['node','-e',BROWSER],cwd=ROOT);chunks=[]
        readers=[threading.Thread(target=lambda:chunks.append(process.stdout.read()),daemon=True),threading.Thread(target=lambda:process.stderr.read(),daemon=True)]
        for reader in readers:reader.start()
        process.stdin.write(json.dumps(dict(url=url,key=business.accounts.current_key(),out=str(attempt),expected=expected)));process.stdin.close()
        try:process.wait(timeout=160)
        finally:
            process.close()
            for reader in readers:reader.join(timeout=5)
        report['browser']=json.loads(''.join(chunks));report['status']=report['browser']['status']
    except Exception as error:report.update(status='failed',failure_type=type(error).__name__)
    finally:
        if process:process.close()
        server.should_exit=True;thread.join(timeout=10)
        report.update(http_stopped=not thread.is_alive(),real_model_calls=0,fake_runtime_requests=runtime.requests,source_hashes=hashes)
        report['source_hashes_unchanged']=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
        if not report['source_hashes_unchanged']:report['status']='provisional_source_changed'
        report['static_hashes']={str(p.relative_to(attempt/'static')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (attempt/'static').rglob('*') if p.is_file()}
        (attempt/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=report['status'],report=str(attempt/'summary.json'),browser=report.get('browser'),failure_type=report.get('failure_type')),ensure_ascii=False))


if __name__=='__main__':main()
