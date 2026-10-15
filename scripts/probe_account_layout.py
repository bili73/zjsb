"""Isolated real HTTP/Edge acceptance for account-owned layouts; no OCR or real users."""
from pathlib import Path
import json
import secrets
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]

BROWSER = r'''
const fs = require('node:fs'), assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async () => {
  const a = JSON.parse(fs.readFileSync(0, 'utf8')), checks = [], errors = [];
  const report = {status:'failed', checks, scope:'Isolated real HTTP and Edge; synthetic accounts; no models'};
  let browser, stage='launch', page;
  try {
    browser = await chromium.launch({channel:'msedge', headless:true});
    const context = await browser.newContext({viewport:{width:1440,height:1100}});
    await context.addInitScript(() => localStorage.setItem('ocr-workbench-entries-v1', '["BANK_CARD"]'));
    page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    const cards = p => p.locator('.type-section > .type-cards > .type-card[data-key]');
    const keys = p => cards(p).evaluateAll(nodes => nodes.map(n => n.dataset.key));
    const ready = p => p.getByRole('button',{name:'自定义入口',exact:true}).waitFor().then(() => p.waitForFunction(() => {
      const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='自定义入口'); return b && !b.disabled;
    }));
    const saved = p => p.evaluate(async()=> (await fetch('/api/v1/auth/me/workbench')).json());
    const login = async(name) => {
      await page.getByPlaceholder('账号',{exact:true}).fill(name);
      await page.getByPlaceholder('密码',{exact:true}).fill(a.password);
      await page.getByRole('button',{name:'进入工作台',exact:true}).click(); await ready(page);
    };
    const edit = p => p.getByRole('button',{name:'自定义入口',exact:true}).click();
    const tuck = (p,key) => p.locator(`.type-section > .type-cards [data-key="${key}"] .card-tuck`).click();
    const finish = async p => { await p.getByRole('button',{name:'完成',exact:true}).click(); await ready(p); };
    await page.goto(a.url); await login('layout_a');
    assert.equal(await page.getByRole('button',{name:'设为默认布局',exact:true}).count(),0);
    stage='legacy isolation';
    const defaults=await keys(page); assert.equal(defaults.length,12); assert.equal((await saved(page)).layout,null);
    checks.push('legacy_shared_key_not_imported');
    stage='twelve card limit and hidden type';
    await page.locator('.type-more summary').click();
    await page.locator('.type-more .type-card').filter({hasText:'面试登记表'}).click();
    assert.equal((await keys(page)).length,12);
    await edit(page); assert.equal(await page.locator('[data-plus-slot]').count(),0);
    await page.getByRole('button',{name:'收纳箱(1)',exact:true}).click();
    await page.getByText('工作台已满12张，请先收纳一张再添加',{exact:true}).waitFor();
    await page.locator('.type-tucked-pop .type-card').filter({hasText:'面试登记表'}).click();
    assert.deepEqual(await keys(page),defaults);
    await tuck(page,'TABLE');
    await page.locator('.type-tucked-pop .type-card').filter({hasText:'面试登记表'}).click();
    const swapped=await keys(page);assert.equal(swapped.length,12);assert.ok(swapped.includes('INTERVIEW_FORM'));assert.ok(!swapped.includes('TABLE'));
    await finish(page);await page.reload();await ready(page);assert.deepEqual(await keys(page),swapped);
    await edit(page);await page.getByRole('button',{name:'恢复默认',exact:true}).click();await finish(page);
    assert.deepEqual(await keys(page),defaults);assert.equal((await saved(page)).layout,null);
    checks.push('twelve_default_hidden_access_and_tuck_before_add');
    stage='drag and tuck';
    await edit(page);
    const first=await cards(page).nth(0).boundingBox(), second=await cards(page).nth(1).boundingBox();
    await page.mouse.move(first.x+first.width/2,first.y+first.height/2); await page.mouse.down();
    await page.waitForTimeout(350); await page.mouse.move(second.x+second.width/2,second.y+second.height/2,{steps:8});
    await page.waitForTimeout(300); await page.mouse.up(); await page.waitForTimeout(350);
    assert.notDeepEqual(await keys(page),defaults);
    await tuck(page,'BANK_CARD'); assert.equal((await saved(page)).layout,null);
    const aLayout=await keys(page); await finish(page);
    assert.deepEqual((await saved(page)).layout,aLayout);
    await page.reload(); await ready(page); assert.deepEqual(await keys(page),aLayout);
    checks.push('real_drag_tuck_explicit_save_and_refresh');
    stage='stale tab conflict';
    const tab=await context.newPage(); await tab.goto(a.url); await ready(tab); await edit(tab); await tuck(tab,'DIPLOMA');
    const draft=await keys(tab);
    await edit(page); await tuck(page,'TABLE'); await finish(page);
    await tab.getByRole('button',{name:'完成',exact:true}).click();
    await tab.locator('.el-alert').filter({hasText:'此账号的布局已在其他页面修改。'}).waitFor();
    assert.deepEqual(await keys(tab),draft);
    assert.equal(await tab.getByRole('button',{name:'完成',exact:true}).isDisabled(),true);
    await tab.getByRole('button',{name:'重新读取',exact:true}).click();
    await tab.locator('.el-message-box__btns .el-button--primary').click(); await ready(tab);
    assert.deepEqual(await keys(tab),(await saved(page)).layout); await tab.close();
    checks.push('stale_tab_preserves_draft_until_confirmed_reload');
    stage='save failure recovery';
    await edit(page); await tuck(page,'DIPLOMA'); const unsaved=await keys(page);
    await page.route('**/api/v1/auth/me/workbench',async route=>{
      if(route.request().method()==='PUT') await route.fulfill({status:500,contentType:'application/json',body:'{"error":{"code":"INTERNAL_ERROR"}}'});
      else await route.continue();
    });
    await page.getByRole('button',{name:'完成',exact:true}).click();
    await page.locator('.el-alert').filter({hasText:'布局保存未确认，当前调整已保留。'}).waitFor();
    assert.deepEqual(await keys(page),unsaved);
    await page.unroute('**/api/v1/auth/me/workbench'); await finish(page);
    assert.deepEqual((await saved(page)).layout,unsaved);
    checks.push('failed_save_preserves_draft_and_retry_succeeds');
    stage='same browser account switch';
    await page.locator('.user-chip').hover(); await page.getByRole('menuitem',{name:'退出登录'}).click();
    await login('layout_b'); assert.deepEqual(await keys(page),defaults); assert.equal((await saved(page)).layout,null);
    await edit(page); await tuck(page,'DIPLOMA'); await finish(page);
    assert.notDeepEqual((await saved(page)).layout,unsaved);
    await page.locator('.user-chip').hover(); await page.getByRole('menuitem',{name:'退出登录'}).click();
    await login('layout_a'); assert.deepEqual(await keys(page),unsaved);
    checks.push('same_browser_accounts_do_not_share_layout');
    stage='reset and restore across browser';
    await edit(page); await page.getByRole('button',{name:'恢复默认',exact:true}).click();
    assert.deepEqual((await saved(page)).layout,unsaved); await finish(page); assert.equal((await saved(page)).layout,null);
    await edit(page); await tuck(page,'BANK_CARD'); await finish(page); const persisted=await keys(page);
    const other=await browser.newContext({viewport:{width:1440,height:1100}}); page=await other.newPage(); await page.goto(a.url); await login('layout_a');
    assert.deepEqual(await keys(page),persisted);
    checks.push('reset_requires_save_and_new_browser_restores_own_layout');
    stage='administrator default';
    const operatorPage=page;
    const adminContext=await browser.newContext({viewport:{width:1440,height:1100}});
    page=await adminContext.newPage(); await page.goto(a.url); await login('layout_admin');
    await edit(page); await tuck(page,'TABLE'); const organizationLayout=await keys(page);
    await page.getByRole('button',{name:'设为默认布局',exact:true}).click();
    await page.getByRole('button',{name:'确认修改',exact:true}).click();
    await page.getByText('默认布局已更新，已有个人布局不变',{exact:true}).waitFor();
    assert.equal((await saved(page)).layout,null);
    assert.deepEqual((await saved(page)).defaults.layout,organizationLayout);
    await operatorPage.reload(); await ready(operatorPage); assert.deepEqual(await keys(operatorPage),persisted);
    const adminPage=page;
    const freshContext=await browser.newContext({viewport:{width:1440,height:1100}});
    page=await freshContext.newPage(); await page.goto(a.url); await login('layout_new');
    assert.deepEqual(await keys(page),organizationLayout); assert.equal((await saved(page)).layout,null);
    checks.push('admin_default_inherited_without_overwriting_custom_accounts_or_saving_personal_draft');
    stage='personal reset inherits administrator default';
    assert.equal(await adminPage.getByRole('button',{name:'恢复系统默认',exact:true}).count(),0);
    await edit(operatorPage); await operatorPage.getByRole('button',{name:'恢复默认',exact:true}).click();
    assert.deepEqual(await keys(operatorPage),organizationLayout);
    assert.deepEqual((await saved(operatorPage)).layout,persisted);
    await finish(operatorPage); assert.equal((await saved(operatorPage)).layout,null);
    await operatorPage.reload(); await ready(operatorPage); assert.deepEqual(await keys(operatorPage),organizationLayout);
    assert.deepEqual((await saved(adminPage)).defaults.layout,organizationLayout);
    checks.push('no_system_reset_and_personal_reset_inherits_admin_default_after_explicit_save');
    await page.screenshot({path:a.out+'/workbench.png',fullPage:true});
    assert.deepEqual(errors,[]); report.status='passed'; report.page_errors=errors;
  } catch(e) { report.stage=stage; report.error=String(e.stack || e); if(page) await page.screenshot({path:a.out+'/failure.png',fullPage:true}).catch(()=>{}); }
  finally { if(browser) await browser.close(); fs.writeFileSync(a.out+'/browser.json',JSON.stringify(report,null,2)); }
  if(report.status!=='passed') process.exitCode=1;
})();
'''


def main():
    import argparse
    import uvicorn
    from test_business_api import FakeRuntime
    from ocr_app.api import create_app
    from ocr_app.business import Business
    from ocr_app.winjob import JobProcess
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=ROOT / 'output/account-layout-20261014-v3')
    base = parser.parse_args().base.resolve()
    out = base / ('browser-' + time.strftime('%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    business = Business(out / 'private/data', key=secrets.token_bytes(32))
    password = secrets.token_urlsafe(24)
    for name in ['layout_a', 'layout_b', 'layout_new']:
        business.accounts.set_user(name, password, name, 'operator')
    business.accounts.set_user('layout_admin', password, 'layout_admin', 'admin')
    runtime = FakeRuntime()
    app = create_app(runtime, base / 'static', out / 'private/session', business=business)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    url = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_config=None, log_level='critical'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    process = None
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.1)
        assert server.started
        process = JobProcess(['node', '-e', BROWSER], cwd=ROOT)
        for stream in [process.stdout, process.stderr]:
            threading.Thread(target=stream.read, daemon=True).start()
        process.stdin.write(json.dumps(dict(url=url, password=password, out=str(out))))
        process.stdin.close()
        result = process.wait(timeout=180)
    finally:
        if process: process.close()
        server.should_exit = True
        thread.join(timeout=10)
    report = json.loads((out / 'browser.json').read_text(encoding='utf-8'))
    print(json.dumps(dict(status=report['status'], checks=len(report['checks']), report=str(out / 'browser.json'),
                          stage=report.get('stage'), error=report.get('error')), ensure_ascii=False))
    assert not thread.is_alive()
    if result: raise SystemExit(result)


if __name__ == '__main__':
    main()
