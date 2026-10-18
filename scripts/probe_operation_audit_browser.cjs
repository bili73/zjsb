// Actual audit component with synthetic responses; never contacts a business service.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const base = path.join(root, 'output/operation-audit');
fs.mkdirSync(base, { recursive: true });
const out = fs.mkdtempSync(path.join(base, 'attempt-'));
const report = { status: 'running', checks: [], errors: [], business_requests: 0 };
let server, browser;
(async () => {
  try {
    const { createServer } = await import(pathToFileURL(path.join(root, 'frontend/node_modules/vite/dist/node/index.js')).href);
    server = await createServer({ root: path.join(root, 'frontend'), logLevel: 'error', server: { host: '127.0.0.1', port: 0, hmr: false } });
    await server.listen(); const origin = server.resolvedUrls.local[0];
    const component = await (await fetch(origin + 'src/components/AuditPanel.vue')).text();
    const main = await (await fetch(origin + 'src/main.ts')).text();
    const vue = component.match(/from\s+"([^"]*\/vue\.js[^"\s]*)"/)[1];
    const element = main.match(/from\s+"([^"]*\/element-plus\.js[^"\s]*)"/)[1];
    browser = await chromium.launch({ executablePath: process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', e => report.errors.push(e.message));
    await page.route('**/api/**', route => { report.business_requests++; return route.abort(); });
    await page.route('**/__fixture', route => route.fulfill({ contentType: 'text/html; charset=utf-8', body: `
      <div id="app" style="padding:24px"></div><script type="module">
      import {createApp,ref,h} from '${vue}'; import ElementPlus from '${element}';
      import AuditPanel from '/src/components/AuditPanel.vue';
      import '/src/style.css'; import '/node_modules/element-plus/dist/index.css';
      const row = {id:'11111111-2222-4333-8444-555555555555', actor:'synthetic-admin',
        identity:{username:'test_admin',display_name:'测试管理员',role:'admin'},event:'upload',description:'上传材料（10份材料）',
        outcome:'success',outcome_label:'成功',created_at:'2026-10-16T00:30:00+00:00',
        task_id:null,run_id:null,batch_id:null,target_type:'account',target_id:'synthetic-admin',
        request_id:'synthetic-request',details:{},object_label:'毕业证 · 2026-10-16 08:00',legacy:false};
      const visible=ref(true), f=window.fixture={calls:[],visible,failQuery:false};
      const api={
        auditOptions:async()=>({actors:[{id:'synthetic-admin',username:'test_admin',display_name:'测试管理员',role:'admin'}],
          events:[{value:'upload',label:'上传材料'}],outcomes:[{value:'success',label:'成功'},{value:'failure',label:'失败'}]}),
        auditPage:async(filters,page,pageSize)=>{f.calls.push({operation:'query',filters,page,pageSize});if(f.failQuery)throw Error('synthetic');
          return {items:[page>1?{...row,event:'retention_changed',description:'文件保留期限：7天 → 15天',object_label:'系统设置'}:{...row,outcome:filters.outcome||'success',outcome_label:filters.outcome==='failure'?'失败':'成功',details:filters.outcome==='failure'?{code:'DECODE_FAILED'}:{}}],next_cursor:null,total:451,page,page_size:pageSize};},
        auditExport:async(filters)=>{f.calls.push({operation:'export',filters});return new Blob(['synthetic workbook'],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});}
      };
      createApp({setup:()=>()=>visible.value?h(AuditPanel,{api}):h('div','已离开审计页面')}).use(ElementPlus).mount('#app');
      </script>` }));
    await page.goto(origin + '__fixture');
    await page.locator('.el-table__body').getByText('测试管理员（test_admin）', { exact: true }).waitFor();
    await page.getByText('2026-10-16 08:30:00', { exact: true }).waitFor();
    await page.locator('.el-pager .number').filter({hasText:/^3$/}).click();
    await page.locator('.el-table__body').getByText('文件保留期限：7天 → 15天', { exact: true }).waitFor();
    assert.equal((await page.evaluate(() => window.fixture.calls.filter(c => c.operation === 'query')))[1].page, 3);
    assert.equal((await page.evaluate(() => window.fixture.calls.filter(c => c.operation === 'query'))).length, 2);
    report.checks.push('UTC+8 display and direct numeric page jump with one request');
    assert.equal(await page.getByRole('button', { name: '查看', exact: true }).count(), 0);
    assert.equal(await page.getByText('修改前', { exact: true }).count(), 0);
    assert.equal(await page.getByText('请求编号', { exact: true }).count(), 0);
    await page.getByText('系统设置', { exact: true }).waitFor();
    report.checks.push('concise settings summary without technical or review detail drawer');
    await page.locator('.filters .el-select').nth(2).click();
    await page.getByRole('option', { name: '失败', exact: true }).click();
    const batch = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
    await page.getByPlaceholder('输入完整批次编号').fill(batch);
    await page.getByRole('button', { name: '查询／回到首页', exact: true }).click();
    await page.waitForFunction(() => window.fixture.calls.filter(c => c.operation === 'query').length === 3);
    const query = await page.evaluate(() => window.fixture.calls.filter(c => c.operation === 'query').at(-1));
    assert.deepEqual(query.filters, { outcome: 'failure', batch_id: batch });
    assert.equal(query.page, 1);
    const downloaded = page.waitForEvent('download');
    await page.getByRole('button', { name: '按筛选条件导出 Excel', exact: true }).click();
    const download = await downloaded;
    assert.match(download.suggestedFilename(), /^操作审计_\d{14}\.xlsx$/);
    assert.deepEqual(await page.evaluate(() => window.fixture.calls.find(c => c.operation === 'export').filters), query.filters);
    report.checks.push('filter reset and matching Excel export');
    await page.screenshot({ animations: 'disabled', path: path.join(out, 'audit-list.png') });
    await page.evaluate(() => { window.fixture.failQuery = true; });
    await page.getByRole('button', { name: '查询／回到首页', exact: true }).click();
    await page.getByText('操作审计读取失败，请稍后重试。', { exact: true }).waitFor();
    assert.equal(await page.locator('.el-table__body .el-table__row').count(), 1, 'failed query keeps previous results');
    report.checks.push('query failure is explicit');
    await page.evaluate(() => { window.fixture.visible.value = false; });
    await page.getByText('已离开审计页面', { exact: true }).waitFor();
    assert.equal(await page.locator('.audit-panel').count(), 0);
    assert.equal(report.business_requests, 0); assert.deepEqual(report.errors, []); report.status = 'passed';
  } catch (error) { report.status = 'failed'; report.failure = String(error.stack); process.exitCode = 1; }
  finally { if (browser) await browser.close(); if (server) await server.close(); fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, checks: report.checks.length, output: out, failure: report.failure })); }
})();
