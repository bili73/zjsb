"""Synthetic headless browser rotation/crop pixel test; isolated HTTP + FakeRuntime."""
import base64
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
const fs=require('node:fs'), assert=require('node:assert/strict');
const {chromium}=require('C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const a=JSON.parse(fs.readFileSync(0,'utf8')), report={status:'failed',checks:[]};let browser,page,stage='launch',posts=0;
 try{
  browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const context=await browser.newContext({viewport:{width:1400,height:1000}});page=await context.newPage();page.setDefaultTimeout(15000);
  let errors=0;page.on('pageerror',()=>errors++);page.on('request',r=>{if(r.url().endsWith('/api/v1/batches')&&r.method()==='POST')posts++;});
  await page.goto(a.url);await page.getByPlaceholder('访问密钥',{exact:true}).fill(a.key);await page.getByRole('button',{name:'进入工作台'}).click();await page.locator('.type-card').filter({hasText:'银行卡'}).click();
  const input={name:'synthetic-vertical-card.png',mimeType:'image/png',buffer:Buffer.from(a.image,'base64')};
  await page.locator('input[type=file]').setInputFiles([input,{...input,name:'synthetic-second-card.png'}]);
  const start=()=>page.getByRole('button',{name:/开始识别/}).click();
  const dimensions=async(w,h)=>page.waitForFunction(([w,h])=>{const im=document.querySelector('.crop-stage img');return im?.complete&&im.naturalWidth===w&&im.naturalHeight===h;},[w,h]);
  const button=name=>page.getByRole('button',{name,exact:true});
  const ready=()=>page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.includes('向右旋转90°')&&!b.disabled));
  const select=async()=>{const b=await page.locator('.crop-stage img').boundingBox();await page.mouse.move(b.x+1,b.y+1);await page.mouse.down();await page.mouse.move(b.x+b.width-1,b.y+b.height-1);await page.mouse.up();};
  const pixels=()=>page.locator('.crop-stage img').evaluate(im=>{const c=document.createElement('canvas');c.width=im.naturalWidth;c.height=im.naturalHeight;const x=c.getContext('2d');x.drawImage(im,0,0);return [[2,2],[c.width-3,2],[2,c.height-3],[c.width-3,c.height-3]].map(([a,b])=>Array.from(x.getImageData(a,b,1,1).data).slice(0,3));});
  stage='right_and_inverse';await start();await dimensions(120,600);await ready();await select();assert.equal(await page.locator('.selection').count(),1);
  await button('向右旋转90°').click();await dimensions(600,120);await ready();assert.equal(await page.locator('.selection').count(),0);assert.deepEqual(await pixels(),a.clockwise);report.checks.push('clockwise_true_pixels_dimensions_and_selection_reset');
  await button('向左旋转90°').click();await dimensions(120,600);await ready();assert.deepEqual(await pixels(),a.original);report.checks.push('left_right_inverse_exact_pixels');
  stage='close_reset';await button('向右旋转90°').click();await dimensions(600,120);await ready();await button('取消（不上传）').click();assert.equal(posts,0);await start();await dimensions(120,600);await ready();assert.equal(await page.locator('.selection').count(),0);assert.deepEqual(await pixels(),a.original);report.checks.push('close_reopen_resets_rotation_no_upload');
  stage='left_crop_first';await button('向左旋转90°').click();await dimensions(600,120);await ready();assert.deepEqual(await pixels(),a.counterclockwise);await select();await page.screenshot({path:a.out+'/counterclockwise-crop.png'});await button('确认并裁下一张').click();await dimensions(120,600);await ready();assert.equal(await page.locator('.selection').count(),0);assert.deepEqual(await pixels(),a.original);assert.equal(posts,0);report.checks.push('next_image_resets_rotation_and_first_crop_not_uploaded_early');
  stage='right_crop_second';await button('向右旋转90°').click();await dimensions(600,120);await ready();await select();await page.screenshot({path:a.out+'/clockwise-crop.png'});const upload=page.waitForResponse(r=>r.url().endsWith('/api/v1/batches')&&r.request().method()==='POST');await button('确认裁图并上传').click();const r=await upload;assert.equal(r.status(),202);const body=await r.json();assert.equal(body.task_ids.length,2);assert.equal(posts,1);assert.equal(errors,0);report.checks.push('one_upload_after_both_crops_no_original_request');report.task_ids=body.task_ids;report.status='passed';report.page_errors=errors;
 }catch(e){report.failure_stage=stage;report.failure_type=e.constructor.name;}
 finally{report.upload_requests=posts;if(browser)await browser.close();report.browser_closed=true;process.stdout.write(JSON.stringify(report));}
})();
'''


def main():
    from PIL import Image,ImageDraw
    from ocr_app.api import create_app
    from ocr_app.business import Business
    from ocr_app.winjob import JobProcess
    from sqlalchemy import text
    import uvicorn
    out=ROOT/'output/bank-crop-rotation-20261008-v1';out.mkdir(exist_ok=True)
    attempt=out/f'attempt-{len(list(out.glob("attempt-*")))+1:03}';attempt.mkdir()
    shutil.copytree(ROOT/'frontend/dist',attempt/'static')
    business=Business(attempt/'private/data',key=secrets.token_bytes(32));business.accounts.accounts[0]['display_name']='合成旋转验收'
    runtime=FakeRuntime();app=create_app(runtime,attempt/'static',attempt/'private/session',business=business)
    sock=socket.socket();sock.bind(('127.0.0.1',0));url=f'http://127.0.0.1:{sock.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app,access_log=False,log_config=None,log_level='critical'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    report=dict(status='failed',scope='Synthetic four-corner pixel markers; headless Edge; isolated real HTTP; FakeRuntime only; no production server/model calls')
    process=None
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.05)
        assert server.started
        colors=[(255,0,0),(0,255,0),(0,0,255),(255,255,0)]
        im=Image.new('RGB',(120,600));draw=ImageDraw.Draw(im)
        for box,color in zip([(0,0,59,299),(60,0,119,299),(0,300,59,599),(60,300,119,599)],colors):draw.rectangle(box,fill=color)
        data=io.BytesIO();im.save(data,format='PNG');original=data.getvalue()
        payload=dict(url=url,key=business.accounts.current_key(),out=str(attempt),image=base64.b64encode(original).decode(),original=colors,clockwise=[colors[i] for i in (2,0,3,1)],counterclockwise=[colors[i] for i in (1,3,0,2)])
        process=JobProcess(['node','-e',BROWSER],cwd=ROOT);chunks=[]
        readers=[threading.Thread(target=lambda:chunks.append(process.stdout.read()),daemon=True),threading.Thread(target=lambda:process.stderr.read(),daemon=True)]
        for reader in readers:reader.start()
        process.stdin.write(json.dumps(payload));process.stdin.close()
        try:process.wait(timeout=180)
        finally:
            process.close()
            for reader in readers:reader.join(timeout=5)
        browser=json.loads(''.join(chunks));report['browser']={k:v for k,v in browser.items() if k!='task_ids'}
        assert browser['status']=='passed'
        pixels=[]
        with business.engine.connect() as connection:
            for identifier in browser['task_ids']:
                row=connection.execute(text('SELECT input_ref,content_hash,meta_enc FROM tasks WHERE id=:id'),{'id':identifier}).mappings().one()
                raw=business.storage.read(row['input_ref']);stored=Image.open(io.BytesIO(raw)).convert('RGB');w,h=stored.size
                actual=[stored.getpixel(p) for p in ((2,2),(w-3,2),(2,h-3),(w-3,h-3))]
                assert w/h>=3.5 and w>450 and h<120
                assert row['content_hash']!=hashlib.sha256(original).hexdigest()
                assert business.storage.unpack(row['meta_enc'])['file_name']=='crop.png'
                pixels.append(dict(width=w,height=h,corners=actual,original_hash_different=True))
        assert pixels[0]['corners']==payload['counterclockwise']
        assert pixels[1]['corners']==payload['clockwise']
        report.update(status='passed',stored_crop_pixels=pixels,stored_crop_count=2)
    except Exception as error:
        report['failure_type']=type(error).__name__
    finally:
        if process:process.close()
        server.should_exit=True;thread.join(timeout=10)
        report.update(http_stopped=not thread.is_alive(),real_model_calls=0,fake_admission_calls=runtime.requests)
        report['provenance']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'frontend/src/bankCrop.ts',ROOT/'frontend/src/components/BankCropDialog.vue',*sorted((attempt/'static').rglob('*'))] if p.is_file()}
        (attempt/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=report['status'],report=str(attempt/'summary.json'),browser=report.get('browser'),failure_type=report.get('failure_type')),ensure_ascii=False))


if __name__=='__main__':main()
