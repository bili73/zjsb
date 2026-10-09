"""Isolated synthetic HTTP + headless Edge review/export acceptance. No OCR models.

CUA was unavailable before browser initialization (Windows ACL helper error).
The approved fallback uses installed Playwright/Edge, never an existing user tab.
Keys flow to the owned child via stdin only; screenshots follow successful login.
"""
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
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
OUT = ROOT / 'output/review-export-browser-20261008-v1'


class FakeRuntime:
    def __init__(self):
        self.alive, self.requests = True, 0

    def start(self):
        pass

    def close(self, graceful=True):
        self.alive = False

    def is_alive(self):
        return self.alive

    def snapshot(self):
        return dict(configured_mode='dual_resident', effective_mode='ocr_unavailable',
                    state='degraded', models=dict(glm_ocr='unloaded', paddleocr_vl='unloaded'), reason_code=None)

    def request(self, operation, **kwargs):
        assert operation == 'recognize' and kwargs.get('max_new_tokens') == 128
        self.requests += 1
        return dict(text='4111 1111 1111 1111', termination_reason='eos')


BROWSER = r'''
const fs=require('node:fs'), assert=require('node:assert/strict');
const {chromium}=require('C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const a=JSON.parse(fs.readFileSync(0,'utf8')), checks=[], errors=[];
 let browser,page,stage='launch';
 const report={status:'failed',mode:'headless Edge / Playwright',checks,pending:[]};
 try{
  browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const context=await browser.newContext({viewport:{width:1500,height:1000},acceptDownloads:true});
  page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  const headers={'X-API-Key':a.key};
  const api=async(method,path,data)=>{const r=await context.request.fetch(a.url+'/api/v1'+path,{method,headers,data});return {status:r.status(),body:await r.json().catch(()=>null),response:r};};
  stage='login';await page.goto(a.url);await page.getByPlaceholder('访问密钥',{exact:true}).fill(a.key);await page.getByRole('button',{name:'进入工作台'}).click();
  await page.locator('.type-card').first().waitFor();assert.equal(await page.locator('.type-card').count(),11);assert.equal(await page.getByPlaceholder('访问密钥',{exact:true}).count(),0);checks.push('dynamic_11_catalogue_login');
  await page.screenshot({path:a.out+'/catalogue.png'});
  const open=async name=>{await page.getByRole('tab',{name:'任务批次'}).click();const cell=page.locator('.batch-collapse .el-collapse-item').filter({hasText:name});await cell.first().locator('.el-collapse-item__header').click();await cell.getByRole('button',{name:'查看',exact:true}).click();await page.locator('.review-editor').waitFor();await page.waitForFunction(()=>{const e=[...document.querySelectorAll('.el-drawer')].find(e=>e.getBoundingClientRect().width>0&&getComputedStyle(e).visibility!=='hidden');if(!e)return false;const r=e.getBoundingClientRect();return r.right<=innerWidth+1&&r.left>=0;});};
  const close=async()=>{await page.locator('.el-drawer:visible .el-drawer__close-btn').click();await page.locator('.review-editor').waitFor({state:'hidden'});};
  stage='certificate_review';await open('synthetic-DIPLOMA.png');
  const editor=page.locator('.review-editor');
  for(const [label,value] of Object.entries(a.certificate)){await editor.locator('.el-form-item').filter({has:page.locator('.el-form-item__label').filter({hasText:label})}).first().locator('input').first().fill(value);}
  const saved=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存修正并重新校验'}).click();const saveResponse=await saved;assert.equal(saveResponse.status(),200);assert.equal((await saveResponse.json()).status,'COMPLETED');checks.push('missing_fields_manual_review_completed');
  stage='preview';const preview=page.waitForResponse(r=>r.url().includes('/preview?')&&r.request().method()==='GET');await page.getByRole('button',{name:'重新读取原图'}).click();const pr=await preview;
  if(pr.status()===403){report.pending.push('GET_FULL_PREVIEW_BACKEND_CONTRACT');report.pending.push('FULL_EXPORT_BACKEND_CONTRACT');}
  else {assert.equal(pr.status(),200);assert.equal(pr.headers()['x-preview-stage'],'corrected');await page.locator('.source-preview figure img').waitFor();checks.push('authenticated_GET_corrected_preview_no_reason');
   stage='single_export';const download=page.waitForEvent('download');await page.locator('.drawer-actions').getByRole('button',{name:'导出 Excel',exact:true}).click();const dl=await download;await dl.saveAs(a.out+'/synthetic-reviewed.xlsx');checks.push('single_full_xlsx_download_no_reason');}
  await page.screenshot({path:a.out+'/reviewed-certificate.png'});await close();
  stage='medical_panel';await open('synthetic-MEDICAL_REPORT.png');stage='medical_items_expand';await page.getByRole('button',{name:'编辑检测项目 / 增删项目'}).click();assert.ok(await editor.getByText('异常诊断',{exact:true}).count());stage='medical_findings_expand';await page.getByRole('button',{name:'编辑报告检查治疗清单'}).click();stage='medical_summary_expand';await page.getByRole('button',{name:'清单声明数 / 增删条目'}).click();await editor.locator('.el-checkbox').filter({hasText:'修正报告清单'}).click();stage='summary_reason';await page.getByPlaceholder('说明修正的原件依据（必填）').fill('合成清单与检测表分开核对');await page.getByRole('button',{name:'新增清单条目',exact:true}).click();await page.getByPlaceholder('清单条目原文',{exact:true}).fill('合成新增条目');await page.getByPlaceholder('报告等级',{exact:true}).fill('B');await page.getByPlaceholder('异常诊断',{exact:true}).fill('合成诊断');await page.getByPlaceholder('原报告清单标题（改声明数量或作用域时必填）').fill('您共有2项异常需进一步检查并治疗：');await editor.locator('.el-form-item').filter({hasText:'原件明确声明数量'}).locator('input').fill('2');const medicalSaved=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存修正并重新校验'}).click();const ms=await medicalSaved;assert.equal(ms.status(),200);const mt=await ms.json();const mr=(await api('GET','/tasks/'+mt.task_id+'/result')).body;assert.equal(mr.report_summary.declared_count,2);assert.equal(mr.report_summary.findings.length,2);assert.equal(mr.stats.total,null);checks.push('medical_summary_add_finding_count_title_real_review');await page.screenshot({path:a.out+'/medical-editor.png'});
  // Discard this deliberately incomplete medical draft; no false completion claim.
  await close();
  stage='generic';await open('synthetic-GENERIC.png');const confirm=editor.locator('.issue-row .el-checkbox');await confirm.click();const oneClick=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存修正并重新校验'}).click();const accepted=await oneClick;assert.equal(accepted.status(),200);assert.equal((await accepted.json()).status,'COMPLETED');assert.equal(accepted.request().postDataJSON().accepted_issues[0].reason,undefined);checks.push('explicit_current_issue_oneclick_without_reason');await editor.locator('textarea').first().fill('合成通用材料人工核对正文');await editor.getByRole('button',{name:'新增键值'}).click();await editor.getByPlaceholder('字段名').fill('合成键');await editor.getByPlaceholder('字段值').fill('合成值');const genericSaved=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存修正并重新校验'}).click();assert.equal((await genericSaved).status(),200);checks.push('generic_text_keyvalue_real_review');await close();
  stage='member';await open('synthetic-HOUSEHOLD_REGISTER.png');await page.getByRole('button',{name:'户口本成员',exact:true}).click();assert.ok(await editor.getByText('成员 1',{exact:true}).count());await page.getByRole('button',{name:'补录遗漏成员',exact:true}).click();await page.getByRole('button',{name:'新增成员',exact:true}).click();const newMembers=editor.locator('.el-collapse-item').filter({hasText:'补录遗漏成员'});await newMembers.locator('.el-form-item').filter({hasText:'姓名（必填）'}).locator('input').fill('合成新增成员');const memberSaved=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存修正并重新校验'}).click();assert.equal((await memberSaved).status(),200);await page.getByRole('button',{name:'户口本成员',exact:true}).click();assert.ok(await editor.getByText('成员 2',{exact:true}).count());checks.push('member_add_with_source_page_metadata_rerender');await close();
  stage='version_conflict';await open('synthetic-DEGREE_CERT.png');await editor.locator('input').first().fill('合成未提交草稿');const task=(await api('GET','/batches/'+a.batches.DEGREE_CERT+'/tasks')).body[0];assert.equal((await api('POST','/tasks/'+task.task_id+'/review',{run_id:task.run_id,expected_revision:task.result_revision})).status,200);const stale=page.waitForResponse(r=>r.url().endsWith('/review')&&r.request().method()==='POST');await editor.getByRole('button',{name:'保存修正并重新校验'}).click();assert.equal((await stale).status(),409);assert.equal(await editor.locator('input').first().inputValue(),'合成未提交草稿');checks.push('409_retains_draft_no_retry');await page.screenshot({path:a.out+'/stale-draft.png'});await page.locator('.el-drawer:visible .el-drawer__close-btn').click();await page.getByRole('button',{name:'确定',exact:true}).click();
  stage='bank_crop';await page.getByRole('tab',{name:'上传识别'}).click();await page.locator('.type-card').filter({hasText:'银行卡'}).click();await page.locator('input[type=file]').setInputFiles({name:'synthetic-full-card.png',mimeType:'image/png',buffer:Buffer.from(a.card,'base64')});let uploads=0;page.on('request',r=>{if(r.url().endsWith('/api/v1/batches')&&r.method()==='POST')uploads++;});await page.getByRole('button',{name:/开始识别/}).click();await page.locator('.crop-stage img').waitFor();assert.equal(uploads,0);const box=await page.locator('.crop-stage img').boundingBox();await page.mouse.move(box.x+box.width*.08,box.y+box.height*.42);await page.mouse.down();await page.mouse.move(box.x+box.width*.92,box.y+box.height*.56);await page.mouse.up();const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/v1/batches')&&r.request().method()==='POST');await page.getByRole('button',{name:'确认裁图并上传'}).click();const up=await uploaded;assert.equal(up.status(),202);assert.equal(uploads,1);checks.push('bank_original_not_uploaded_crop_real_admission_stub');
  stage='batch_export_gate';await page.getByRole('tab',{name:'任务批次'}).click();assert.ok(await page.getByText(/尚未完成复核/).count());checks.push('unreviewed_batch_export_disabled');
  stage='viewer_controls';page=await context.newPage();await page.goto(a.url);await page.getByPlaceholder('访问密钥',{exact:true}).fill(a.viewer_key);await page.getByRole('button',{name:'进入工作台'}).click();await page.locator('.type-card').first().waitFor();await open('synthetic-DIPLOMA.png');assert.equal(await page.locator('.drawer-actions').getByRole('button',{name:'导出 Excel',exact:true}).isDisabled(),true);assert.equal(await page.getByRole('button',{name:'重新读取原图'}).isDisabled(),true);checks.push('viewer_preview_export_controls_disabled');await page.screenshot({path:a.out+'/viewer-controls.png'});
  assert.equal(errors.length,0);report.status=report.pending.length?'partial':'passed';
 }catch(e){if(page&&checks.length)await page.screenshot({path:a.out+'/failure.png'}).catch(()=>{});report.failure_stage=stage;report.failure_type=e.constructor.name;if(checks.length)report.safe_locator_failure=String(e.message).split('\n')[0].replaceAll(a.key,'[redacted]').slice(0,180);report.failure_category=/strict mode violation/.test(e.message)?'AMBIGUOUS_TEST_LOCATOR':/Timeout/.test(e.message)?'WAIT_TIMEOUT':'OTHER';/* never persist assertion source, credentials or exception text */}
 finally{report.page_errors=errors.length;if(browser)await browser.close();report.browser_closed=true;process.stdout.write(JSON.stringify(report));}
})();
'''


def main():
    import httpx
    import uvicorn
    from PIL import Image, ImageDraw
    from ocr_app.api import create_app
    from ocr_app.business import Business
    from ocr_app.extraction import extract_result, _medical_item
    from ocr_app.winjob import JobProcess

    OUT.mkdir(exist_ok=True)
    attempt = OUT / f'attempt-{1 + len(list(OUT.glob("attempt-*"))):03}'
    attempt.mkdir()
    shutil.copytree(ROOT / 'frontend/dist', attempt / 'static')
    runtime = FakeRuntime()
    business = Business(attempt / 'private/data', key=secrets.token_bytes(32))
    business.accounts.accounts[0]['display_name'] = '合成验收账号'
    key = business.accounts.current_key()
    viewer_key = secrets.token_urlsafe(32)
    business.accounts.accounts.append(dict(user_id=str(uuid4()),display_name='合成只读账号',role='viewer',key=viewer_key))
    app = create_app(runtime, attempt / 'static', attempt / 'private/session', business=business)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    url = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_config=None, log_level='critical'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    report = dict(scope='Synthetic inputs, real loopback HTTP, headless Edge. Fake OCR admission only; no OCR accuracy claims.',
                  cua_status='blocked_before_initialization_by_sandbox_acl', status='failed', http_checks=[])
    backend_paths = [ROOT / 'backend/ocr_app' / name for name in ('api.py','routes.py','review.py','preview.py','exporting.py','task_store.py')]
    backend_hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in backend_paths}
    process = None
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        picture = Image.new('RGB', (800, 500), 'white')
        ImageDraw.Draw(picture).text((60, 230), 'SYNTHETIC 4111 1111 1111 1111', fill='black')
        raw = io.BytesIO(); picture.save(raw, format='PNG'); image = raw.getvalue()
        batches = {}
        with httpx.Client(base_url=url, headers={'X-API-Key': key}, timeout=20) as client:
            profiles = client.get('/api/v1/doc-types').json()
            assert len(profiles) == 11
            for profile in profiles:
                kind = profile['doc_type']
                upload = image
                if kind == 'BANK_CARD':
                    cropped = io.BytesIO();picture.crop((50,220,750,270)).save(cropped,format='PNG');upload=cropped.getvalue()
                response = client.post('/api/v1/batches', data={'doc_type_hint': kind}, files={'files': (f'synthetic-{kind}.png', upload, 'image/png')})
                assert response.status_code == 202
                created = response.json()
                batches[kind] = created['batch_id']
                task = business.store.claim_next()
                page_id = business.store.save_page(task, 1, image, 800, 500)
                result = extract_result([], kind)
                if kind == 'MEDICAL_REPORT':
                    result['items'] = [_medical_item('合成指标', '3', 'u', '1-5', None, None, {'page': 1}, ['synthetic'])]
                    result['report_summary'] = dict(scope='follow_up_required', declared_count=1, count_check='unverified', sources=[dict(page=1)], findings=[dict(finding_id=str(uuid4()),reported_number='1',text='合成报告条目',risk_grade='B',diagnosis='合成诊断',sources=[dict(page=1)])])
                if kind == 'GENERIC':
                    from ocr_app.extraction import issue
                    result['generic']['full_text']='合成通用原文'
                    result['review_issues']=[issue('CONFIDENCE_UNAVAILABLE','请对照原件核对合成正文',True)]
                if kind == 'HOUSEHOLD_REGISTER':
                    result['members'] = [dict(name=dict(key='name',label='成员姓名',value='合成成员',confidence=None,confidence_method='unavailable',need_review=False,review_issues=[]))]
                result.update(status='NEED_REVIEW', pages=[dict(page_id=page_id,page_index=1,width=800,height=500,extraction_method='ocr',regions=[])])
                assert business.store.publish(task,result)
            report['http_checks'].append('11_catalogue_and_isolated_published_synthetic_cases')
        payload = dict(url=url,key=key,viewer_key=viewer_key,out=str(attempt),batches=batches,card=base64.b64encode(image).decode(),
                       certificate={'姓名':'合成人员','学校':'合成大学','专业':'合成专业','学历':'本科','毕业':'2020-06','证书编号':'0012345678901234'})
        process = JobProcess(['node', '-e', BROWSER], cwd=ROOT)
        stdout=[]
        readers=[threading.Thread(target=lambda:stdout.append(process.stdout.read()),daemon=True), threading.Thread(target=lambda:process.stderr.read(),daemon=True)]
        for reader in readers: reader.start()
        process.stdin.write(json.dumps(payload));process.stdin.close()
        try:
            process.wait(timeout=240)
        finally:
            process.close()
            for reader in readers:reader.join(timeout=5)
        report['browser']=json.loads(''.join(stdout))
        report['status']=report['browser']['status']
        if report['status'] == 'passed':
            from openpyxl import load_workbook
            with httpx.Client(base_url=url, headers={'X-API-Key':key}, timeout=20) as client:
                task = client.get(f"/api/v1/batches/{batches['DIPLOMA']}/tasks").json()[0]
                identifier = task['task_id']
                result = client.get(f'/api/v1/tasks/{identifier}/result').json()
                assert next(f['value'] for f in result['fields'] if f['key']=='certificate_no') == '0012345678901234'
                params = dict(run_id=task['run_id'],result_revision=task['result_revision'],page=1)
                assert httpx.get(url+f'/api/v1/tasks/{identifier}/preview',params=params).status_code == 401
                assert client.get(f'/api/v1/tasks/{identifier}/preview',params=dict(params,result_revision=task['result_revision']+1)).status_code == 409
                report['http_checks'].append('full_result_and_preview_auth_revision_guards')
                exports=[]
                for masked in (True,False):
                    response = client.post('/api/v1/export',json=dict(task_ids=[identifier],masked=masked,versions=[dict(task_id=identifier,run_id=task['run_id'],result_revision=task['result_revision'])]))
                    assert response.status_code == 200
                    book=load_workbook(io.BytesIO(response.content),read_only=True)
                    values=[[cell.value for row in sheet for cell in row] for sheet in book]
                    assert any('0012345678901234' in sheet for sheet in values)
                    exports.append(values)
                assert exports[0] == exports[1]
                pending = client.get(f"/api/v1/batches/{batches['ID_CARD_BACK']}/tasks").json()[0]
                assert client.post('/api/v1/export',json=dict(task_ids=[identifier,pending['task_id']])).status_code == 409
                report['http_checks'].append('legacy_masked_true_false_both_full_and_unreviewed_batch_blocked')
                viewer_headers={'X-API-Key':viewer_key}
                me=client.get('/api/v1/auth/me',headers=viewer_headers).json()
                assert me['permissions'] == []
                assert client.get(f'/api/v1/tasks/{identifier}/result',headers=viewer_headers).status_code == 200
                assert client.get(f'/api/v1/tasks/{identifier}/preview',params=params,headers=viewer_headers).status_code == 403
                assert client.post('/api/v1/export',json=dict(task_ids=[identifier]),headers=viewer_headers).status_code == 403
                report['http_checks'].append('viewer_full_result_but_preview_export_403_permissions_empty')
    except Exception as error:
        report['status']='failed'
        report['failure_type']=type(error).__name__
    finally:
        if process:
            process.close()
        server.should_exit=True;thread.join(timeout=10)
        report['http_stopped']=not thread.is_alive()
        report['fake_admission_calls']=runtime.requests
        report['real_model_calls']=0
        report['backend_provenance']=backend_hashes
        report['backend_hashes_unchanged']=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in backend_hashes.items())
        if not report['backend_hashes_unchanged']:
            report['status']='provisional_backend_changed'
        report['provenance']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*sorted((attempt/'static').rglob('*'))] if p.is_file()}
        (attempt/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=report['status'],report=str(attempt/'summary.json'),failure_type=report.get('failure_type'),browser=report.get('browser')),ensure_ascii=False))


if __name__ == '__main__':
    main()
