// Real SourcePreview component, synthetic delayed images, no backend or OCR calls.
// Run after frontend dependencies are installed: node scripts/probe_source_navigation_browser.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'output/source-navigation-layout');
fs.mkdirSync(output, { recursive: true });
const out = fs.mkdtempSync(path.join(output, 'attempt-'));
const report = { status: 'running', checks: [], errors: [], business_requests: 0, model_calls: 0 };
let server, browser;

(async () => {
  try {
    const { createServer } = await import(pathToFileURL(path.join(root, 'frontend/node_modules/vite/dist/node/index.js')).href);
    server = await createServer({ root: path.join(root, 'frontend'), logLevel: 'error', server: { host: '127.0.0.1', port: 0 } });
    await server.listen();
    const origin = server.resolvedUrls.local[0];
    const component = await (await fetch(origin + 'src/components/SourcePreview.vue')).text();
    const main = await (await fetch(origin + 'src/main.ts')).text();
    const vue = component.match(/from\s+"([^"]*\/vue\.js[^"\s]*)"/)[1];
    const elementPlus = main.match(/from\s+"([^"]*\/element-plus\.js[^"\s]*)"/)[1];
    report.component_sha256 = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(root, 'frontend/src/components/SourcePreview.vue'))).digest('hex');
    browser = await chromium.launch({ executablePath: process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });

    async function open(delays = {}, kind = 'MEDICAL_REPORT', ocrEnabled = true, localKind = 'image') {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      page.on('pageerror', error => report.errors.push(error.message));
      await page.route('**/api/**', route => { report.business_requests++; return route.abort(); });
      await page.route('**/__fixture', route => route.fulfill({ contentType: 'text/html', body: `
        <div id="app"></div><script type="module">
        import {createApp,ref,h} from '${vue}'; import ElementPlus from '${elementPlus}';
        import SourcePreview from '/src/components/SourcePreview.vue'; import '/src/style.css'; import '/node_modules/element-plus/dist/index.css';
        window.scrollCalls=[];window.previewRequests=[];window.revoked=[]; const native=Element.prototype.scrollIntoView;
        const revoke=URL.revokeObjectURL.bind(URL);URL.revokeObjectURL=url=>{window.revoked.push(url);revoke(url)};
        Element.prototype.scrollIntoView=function(options){window.scrollCalls.push({page:this.closest('[data-page]')?.dataset.page,time:performance.now(),behavior:options?.behavior});return native.call(this,options)};
        const source=ref(null),task=ref({task_id:'synthetic',run_id:'one',result_revision:1,page_count:8,actual_source_page_count:8,doc_type:'${kind}'});
        const api={preview:async(t,n,signal,reason,rendition='original')=>{window.previewRequests.push({page:n,rendition});const response=await fetch('/synthetic-image?page='+n+'&rendition='+rendition,{signal});if(!response.ok)throw Error('Synthetic preview failure');return{blob:await response.blob(),corrected:true}}};
        const local={kind:'${localKind}',url:${localKind === 'pdf' ? "'about:blank'" : "URL.createObjectURL(new Blob(['<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"3000\"><rect width=\"800\" height=\"3000\" fill=\"white\"/></svg>'],{type:'image/svg+xml'}))"}};
        window.select=(page,box=true)=>source.value={page,...(box?{bbox:[.1,.6,.9,.65]}:{})};
        createApp({setup:()=>()=>h('main',{},[
          ...[5,7].map(n=>h('button',{id:'locate-'+n,onClick:()=>window.select(n)},'Locate '+n)),
          h('button',{id:'reset',onClick:()=>{source.value=null;task.value={...task.value,run_id:'two'}}},'New version'),
          h('button',{id:'unmount',onClick:()=>task.value=null},'Close'),
          task.value?h('aside',{class:'fixture-pane',style:'width:500px;height:680px;overflow:auto;position:relative;margin:40px'},[
            h(SourcePreview,{task:task.value,api,source:source.value,canWrite:true,ocrEnabled:${ocrEnabled},preview:local})]):null
        ])}).use(ElementPlus).mount('#app');
        </script>` }));
      await page.route('**/synthetic-image?*', async route => {
        const params = new URL(route.request().url()).searchParams;
        const n = Number(params.get('page'));
        const height = params.get('rendition') === 'display' ? 1800 : 3000;
        await new Promise(resolve => setTimeout(resolve, delays[n] ?? (180 + n * 20)));
        await route.fulfill(n === delays.failPage ? { status: 503, body: 'Synthetic failure' } : {
          contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="${height * 4 / 15}" height="${height}"><rect width="100%" height="100%" fill="white"/><text x="40" y="70" font-size="32">Synthetic page ${n}</text><rect x="10%" y="60%" width="80%" height="5%" fill="pink"/></svg>`,
        }).catch(() => {});
      });
      await page.goto(origin + '__fixture');
      await page.locator('#locate-5').waitFor();
      return page;
    }

    async function position(page) {
      return page.evaluate(() => {
        const box = document.querySelector('.bbox-overlay')?.getBoundingClientRect();
        const pane = document.querySelector('.fixture-pane')?.getBoundingClientRect();
        return { top: box?.top, bottom: box?.bottom, paneTop: pane?.top, paneBottom: pane?.bottom,
          visible: Boolean(box && pane && box.top >= pane.top - 2 && box.bottom <= pane.bottom + 2),
          page: document.querySelector('.bbox-overlay')?.closest('[data-page]')?.dataset.page,
          scrollCalls: window.scrollCalls.length };
      });
    }

    async function check(name, run) {
      const entry = { name, passed: false };
      try { entry.details = await run(); entry.passed = true; }
      catch (error) { entry.failure = String(error.message).slice(0, 700); }
      report.checks.push(entry);
    }

    for (const kind of ['image', 'pdf']) await check('local_' + kind + '_mounts_only_when_open', async () => {
      const page = await open({ 1: 20 }, 'MEDICAL_REPORT', true, kind);
      try {
        const local = page.locator('.local-preview'), content = local.locator('iframe, .local-image');
        assert.equal(await local.getAttribute('open'), null);
        assert.equal(await content.count(), 0);
        await local.locator('summary').click(); await content.waitFor();
        await local.locator('summary').click(); await content.waitFor({ state: 'detached' });
        return { closed_content_elements: await content.count() };
      } finally { await page.close(); }
    });
    await check('display_list_and_original_enlargement_with_close', async () => {
      const page = await open({ 1: 20 }, 'DIPLOMA', false);
      try {
        const image = page.locator('[data-page="1"] .page-image img');
        await image.waitFor();
        await page.waitForFunction(() => document.querySelector('[data-page="1"] .page-image img')?.naturalHeight > 0);
        const displayUrl = await image.getAttribute('src');
        assert.equal(await image.evaluate(el => el.naturalHeight), 1800);
        assert.ok(await page.evaluate(() => window.previewRequests.every(r => r.rendition === 'display')));
        await image.click();
        const original = page.locator('.el-image-viewer__img');
        await original.waitFor();
        await page.waitForFunction(() => document.querySelector('.el-image-viewer__img')?.naturalHeight === 3000);
        const originalUrl = await original.getAttribute('src');
        assert.notEqual(originalUrl, displayUrl);
        assert.equal(await page.evaluate(() => window.previewRequests.at(-1).rendition), 'original');
        await page.locator('.el-image-viewer__close').click(); await original.waitFor({ state: 'detached' });
        assert.ok(await page.evaluate(url => window.revoked.includes(url), originalUrl));
        assert.equal(await image.getAttribute('src'), displayUrl);
        await page.screenshot({ path: path.join(out, 'display-after-original-close.png') });
        return { display_height: 1800, original_height: 3000, original_url_revoked: true };
      } finally { await page.close(); }
    });

    for (const delay of [180, 350, 600]) await check('first_click_with_preceding_loads_' + delay, async () => {
      const page = await open({ 1: delay + 20, 2: delay + 40, 3: delay + 60, 4: delay + 80, 5: 50 });
      try {
        await page.locator('#locate-5').click(); await page.waitForTimeout(2500);
        const result = await position(page); assert.equal(result.visible, true, JSON.stringify(result));
        assert.deepEqual(await page.evaluate(() => [...new Set(window.scrollCalls.map(call => call.behavior))]), ['smooth']);
        await page.screenshot({ path: path.join(out, `first-click-${delay}.png`) });
        return result;
      } finally { await page.close(); }
    });
    await check('latest_selection_wins_after_old_response', async () => {
      const page = await open({ 5: 1400, 7: 50 });
      try {
        await page.locator('#locate-5').click(); await page.locator('#locate-7').click(); await page.waitForTimeout(3000);
        const result = await position(page); assert.equal(result.page, '7'); assert.equal(result.visible, true, JSON.stringify(result)); return result;
      } finally { await page.close(); }
    });
    await check('same_page_reselection_after_manual_page_jump', async () => {
      const page = await open({ 5: 50 });
      try {
        await page.locator('#locate-5').click(); await page.waitForTimeout(2000);
        await page.locator('.source-preview input').fill('1'); await page.getByRole('button', { name: '跳页', exact: true }).click(); await page.waitForTimeout(1000);
        await page.locator('#locate-5').click(); await page.waitForTimeout(1200);
        const result = await position(page); assert.equal(result.visible, true, JSON.stringify(result)); return result;
      } finally { await page.close(); }
    });
    await check('warm_navigation_has_visible_intermediate_scroll_positions', async () => {
      const page = await open({ 5: 50 });
      try {
        await page.locator('#locate-5').click(); await page.waitForTimeout(2500);
        await page.locator('.source-preview input').fill('1'); await page.getByRole('button', { name: '跳页', exact: true }).click(); await page.waitForTimeout(1500);
        await page.evaluate(() => {
          window.motion = []; const pane = document.querySelector('.fixture-pane');
          let frames = 0; const sample = () => { window.motion.push(pane.scrollTop); if (++frames < 110) requestAnimationFrame(sample); };
          requestAnimationFrame(sample);
        });
        await page.locator('#locate-5').click(); await page.waitForFunction(() => window.motion.length === 110, null, { timeout: 5000 });
        const samples = await page.evaluate(() => window.motion);
        const start = samples[0], end = samples.at(-1), distance = Math.abs(end - start);
        const intermediate = samples.filter(value => Math.abs(value - start) > distance * .1 && Math.abs(value - start) < distance * .9);
        assert.ok(distance > 1000, 'Expected a long navigation');
        assert.ok(new Set(intermediate).size > 8, JSON.stringify({ start, end, intermediate }));
        assert.ok(Math.max(...samples.slice(1).map((value, index) => Math.abs(value - samples[index]))) < distance * .4, 'Unexpected instantaneous scroll jump');
        assert.equal((await position(page)).visible, true);
        return { distance, intermediate_positions: new Set(intermediate).size };
      } finally { await page.close(); }
    });
    await check('preview_resize_realigns_without_another_image_load', async () => {
      const page = await open({ 5: 50 });
      try {
        await page.locator('#locate-5').click(); await page.waitForTimeout(2000);
        await page.locator('.fixture-pane').evaluate(el => { el.style.width = '350px'; });
        await page.waitForFunction(() => { const box=document.querySelector('.bbox-overlay').getBoundingClientRect(),pane=document.querySelector('.fixture-pane').getBoundingClientRect();return Math.abs((box.top+box.bottom-pane.top-pane.bottom)/2)<2; }, null, { timeout: 3000 });
        const result = await position(page);
        assert.equal(result.visible, true, JSON.stringify(result));
        assert.ok(Math.abs((result.top + result.bottom) / 2 - (result.paneTop + result.paneBottom) / 2) < 2, JSON.stringify(result));
        return result;
      } finally { await page.close(); }
    });
    await check('manual_wheel_cancels_late_alignment', async () => {
      const page = await open({ 1: 1500, 2: 1700, 3: 1900, 5: 50 });
      try {
        await page.locator('#locate-5').click(); await page.locator('.bbox-overlay').waitFor();
        await page.mouse.move(250, 400); await page.mouse.wheel(0, 500);
        const calls = (await position(page)).scrollCalls; await page.waitForTimeout(2500);
        assert.equal((await position(page)).scrollCalls, calls); return { calls_after_intent: calls };
      } finally { await page.close(); }
    });
    await check('manual_page_jump_cancels_unloaded_source', async () => {
      const page = await open({ 1: 50, 5: 1400 });
      try {
        await page.locator('#locate-5').click(); await page.waitForTimeout(150);
        await page.locator('.source-preview input').fill('1');
        await page.getByRole('button', { name: '跳页', exact: true }).click();
        const calls = (await position(page)).scrollCalls; await page.waitForTimeout(2200);
        assert.equal((await position(page)).scrollCalls, calls); return { calls_after_jump: calls };
      } finally { await page.close(); }
    });
    await check('missing_box_uses_page_fallback', async () => {
      const page = await open({ 5: 50 });
      try {
        await page.evaluate(() => window.select(5, false)); await page.waitForTimeout(2500);
        assert.equal(await page.locator('.bbox-overlay').count(), 0);
        const visible = await page.locator('[data-page="5"]').evaluate(el => { const r=el.getBoundingClientRect(),p=el.closest('aside').getBoundingClientRect();return r.top<p.bottom&&r.bottom>p.top; });
        assert.equal(visible, true); return { whole_page_visible: visible };
      } finally { await page.close(); }
    });
    for (const action of ['reset', 'unmount']) await check(action + '_cancels_late_navigation', async () => {
      const page = await open({ 5: 1400 });
      try {
        await page.locator('#locate-5').click(); await page.locator('#' + action).click();
        const calls = await page.evaluate(() => window.scrollCalls.length); await page.waitForTimeout(2200);
        assert.equal(await page.evaluate(() => window.scrollCalls.length), calls); assert.equal(await page.locator('.bbox-overlay').count(), 0); return { calls };
      } finally { await page.close(); }
    });
    await check('preview_failure_keeps_retry_and_whole_page', async () => {
      const page = await open({ 5: 50, failPage: 5 });
      try {
        await page.locator('#locate-5').click(); await page.locator('[data-page="5"] .page-error').waitFor();
        assert.equal(await page.locator('[data-page="5"]').getByRole('button', { name: '重试' }).count(), 1);
        assert.equal(await page.locator('.bbox-overlay').count(), 0); return { retry_visible: true };
      } finally { await page.close(); }
    });
    assert.equal(report.business_requests, 0); assert.deepEqual(report.errors, []);
    report.status = report.checks.every(check => check.passed) ? 'passed' : 'failed';
  } catch (error) { report.status = 'failed'; report.failure = String(error.message).slice(0, 700); }
  finally {
    if (browser) await browser.close();
    if (server) await server.close();
    report.resources_closed = true;
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ ...report, output: out }, null, 2));
    if (report.status !== 'passed') process.exitCode = 1;
  }
})();
