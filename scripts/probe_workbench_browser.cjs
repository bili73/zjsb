// Reproducible CPU-only browser smoke: synthetic fixtures, isolated loopback API, no model imports.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const outputRoot = path.join(root, 'output');
const output = path.resolve(process.argv[2] || path.join(outputRoot, 'workbench-browser-20261008-v1'));
if (!output.startsWith(outputRoot + path.sep)) throw new Error('OUTPUT_MUST_BE_ISOLATED');
fs.mkdirSync(output, { recursive: true });
let attempt = 1;
while (fs.existsSync(path.join(output, `attempt-${String(attempt).padStart(3, '0')}`))) attempt++;
const out = path.join(output, `attempt-${String(attempt).padStart(3, '0')}`);
fs.mkdirSync(out);
const dist = path.join(root, 'frontend/dist');
const fixtureKey = crypto.randomBytes(24).toString('base64url'); // Never logged or saved.
const uuid = n => `12345678-1234-4321-9876-${String(n).padStart(12, '0')}`;
const checks = [], errors = [], batches = [], taskMap = new Map();
let uploadCount = 0, failUpload = false, stage = 'setup', browser, context, page;
const report = { status: 'running', scope: 'Synthetic HTTP fixture and real Edge; no OCR accuracy, real API integration or GPU concurrency claim', checks };
const save = () => fs.writeFileSync(path.join(out, 'summary.json'), JSON.stringify(report, null, 2));
save();

function pdf() {
  const stream = text => `<< /Length ${Buffer.byteLength(text)} >>\nstream\n${text}\nendstream`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 500] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 500] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    stream('BT /F1 20 Tf 40 420 Td (SYNTHETIC SOURCE PAGE 1) Tj ET'), stream('BT /F1 20 Tf 40 420 Td (SYNTHETIC SOURCE PAGE 2) Tj ET')];
  let text = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((body, i) => { offsets.push(Buffer.byteLength(text)); text += `${i + 1} 0 obj\n${body}\nendobj\n`; });
  const xref = Buffer.byteLength(text);
  text += `xref\n0 8\n0000000000 65535 f \n${offsets.slice(1).map(n => String(n).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(text);
}
function task(id, name, batchId) {
  return { task_id: id, batch_id: batchId, run_id: uuid(500 + taskMap.size), result_revision: 1,
    status: 'NEED_REVIEW', progress: 100, cancel_requested: false, page_count: name.endsWith('.pdf') ? 2 : 1,
    pages: [], file_name: name, doc_type: 'MEDICAL_REPORT', extract_options: { abnormal_only: false } };
}
function result(t) {
  const source = { page: t.page_count, region_id: uuid(999), extraction_method: 'pdf_text', bbox_kind: 'row', bbox: [0.1, 0.1, 0.8, 0.2], raw_text: 'SYNTHETIC_SOURCE_NOT_FOR_RENDER' };
  const item = (n, name, alias, flag, basis, raw) => ({ item_id: uuid(800 + n), name, alias, category: n === 2 ? '尿常规' : '血常规', result_raw: raw,
    unit: '合成单位', reference_range: '合成参考', abnormal_flag: flag, abnormal_basis: basis, reported_abnormal_marker: flag === 'HIGH' ? '↑' : null,
    confidence: null, confidence_method: 'unavailable', need_review: true, review_issues: [], source });
  return { task_id: t.task_id, run_id: t.run_id, result_revision: t.result_revision, status: t.status, doc_type: 'MEDICAL_REPORT', review_issues: [],
    basic_info: { sample: { key: 'sample', label: '合成样本编号', value: '****2468', confidence: null, confidence_method: 'unavailable', need_review: true, review_issues: [], source } },
    items: [item(1, '合成白细胞', 'WBC', 'HIGH', 'report_marker', '8.2↑'), item(2, '合成阳性项', 'TEST', 'POSITIVE', 'unknown', '+'), item(3, '合成正常项', 'HGB', 'NORMAL', 'reference_comparison', '140')],
    stats: { total: null, normal: null, abnormal: null, unknown: null, categories: [] }, abnormal_summary: [], limitations: ['合成测试结果，不能作为完整报告'],
    report_summary: { scope: 'follow_up_required', declared_count: 1, count_check: 'match', sources: [source], findings: [{ finding_id: uuid(900), reported_number: '1', text: '合成检查提示，仅用于界面测试', sources: [source] }] } };
}
function updateTasks() {
  for (const t of taskMap.values()) if (t.finishAt && Date.now() >= t.finishAt) {
    t.status = t.cancel_requested ? 'CANCELLED' : 'NEED_REVIEW'; t.progress = 100; delete t.finishAt;
  }
}
const server = http.createServer((request, response) => {
  const json = (value, status = 200) => { response.writeHead(status, { 'Content-Type': 'application/json', 'X-Request-ID': uuid(1) }); response.end(JSON.stringify(value)); };
  const url = new URL(request.url, 'http://127.0.0.1');
  if (url.pathname === '/health') return json({ status: 'ok', version: '1.12.0', queue_depth: 0, components: { db: 'ok', worker: 'ok', storage: 'ok' }, runtime: { configured_mode: 'dual_resident', effective_mode: 'dual_resident', state: 'ready', models: { glm_ocr: 'ready', paddleocr_vl: 'ready' }, reason_code: null } });
  if (url.pathname.startsWith('/api/v1/')) {
    if (request.headers['x-api-key'] !== fixtureKey) return json({ code: 'UNAUTHORIZED', error_id: 'e_syntheticAuth' }, 401);
    if (url.pathname.endsWith('/auth/me')) return json({ user_id: uuid(1), display_name: '合成测试账号', role: 'operator', permissions: ['rerun'] });
    if (url.pathname === '/api/v1/batches' && request.method === 'POST') {
      uploadCount++; const chunks = [];
      request.on('data', chunk => chunks.push(chunk)); request.on('end', () => {
        if (failUpload) return json({ code: 'INTERNAL_ERROR', error_id: 'e_syntheticUpload' }, 500);
        const names = [...Buffer.concat(chunks).toString('latin1').matchAll(/name="files"; filename="([^"]+)"/g)].map(match => match[1]);
        const batchId = uuid(100 + batches.length); const ids = names.map((_, index) => uuid(uploadCount * 10 + names.length - index));
        names.forEach((name, i) => taskMap.set(ids[i], task(ids[i], name, batchId)));
        batches.unshift({ batch_id: batchId, display_name: '合成上传批次', status: 'PROCESSING', file_count: names.length, task_ids: ids, file_names: names });
        json({ batch_id: batchId, task_ids: ids }, 202);
      }); return;
    }
    if (url.pathname === '/api/v1/batches') return json({ items: batches.map(({ task_ids, file_names, ...b }) => b), total: batches.length, page: 1, page_size: 10 });
    const batchId = url.pathname.match(/\/batches\/([^/]+)\/tasks$/)?.[1];
    if (batchId) { updateTasks(); return json((batches.find(b => b.batch_id === batchId)?.task_ids ?? []).slice().reverse().map(id => taskMap.get(id))); }
    const match = url.pathname.match(/\/tasks\/([^/]+)\/(result|cancel|rerun)$/);
    if (match) {
      const t = taskMap.get(match[1]); if (!t) return json({ code: 'NOT_FOUND' }, 404);
      if (match[2] === 'result') return json(result(t));
      const chunks = []; request.on('data', x => chunks.push(x)); request.on('end', () => {
        const version = JSON.parse(Buffer.concat(chunks));
        if (version.run_id !== t.run_id || version.expected_revision !== t.result_revision) return json({ code: 'RESULT_VERSION_CONFLICT' }, 409);
        if (match[2] === 'rerun') { t.run_id = uuid(1000 + uploadCount); t.result_revision++; t.status = 'QUEUED'; t.progress = 0; t.cancel_requested = false; }
        else t.cancel_requested = true;
        t.finishAt = Date.now() + 1300; json(t, 202);
      }); return;
    }
    return json({ code: 'NOT_FOUND' }, 404);
  }
  const target = path.resolve(dist, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
  if (!target.startsWith(dist + path.sep) || !fs.existsSync(target) || !fs.statSync(target).isFile()) { response.writeHead(404); return response.end(); }
  response.writeHead(200, { 'Content-Type': target.endsWith('.js') ? 'text/javascript' : target.endsWith('.css') ? 'text/css' : 'text/html' }); fs.createReadStream(target).pipe(response);
});
async function wait(check) { await page.waitForFunction(check, undefined, { timeout: 15000 }); }
async function run() {
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await chromium.launch({ executablePath: process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
    context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
      window.previewAudit = { active: [], revoked: 0, detailScrolls: 0 };
      URL.createObjectURL = blob => { const url = create(blob); window.previewAudit.active.push(url); return url; };
      URL.revokeObjectURL = url => { window.previewAudit.active = window.previewAudit.active.filter(x => x !== url); window.previewAudit.revoked++; revoke(url); };
      const scroll = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (...args) { if (this.classList.contains('task-detail')) window.previewAudit.detailScrolls++; return scroll.apply(this, args); };
    });
    page = await context.newPage(); page.on('pageerror', () => errors.push('PAGE_ERROR'));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    stage = 'auth'; await page.locator('#api-key').fill(fixtureKey); await page.getByRole('button', { name: '验证并连接' }).click(); await page.locator('.upload-form').waitFor();
    const pngs = await page.evaluate(() => ['#2864a0', '#c96a3b'].map((color, index) => {
      const canvas = document.createElement('canvas'); canvas.width = 440; canvas.height = 560; const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 440, 560); ctx.fillStyle = color; ctx.fillRect(30, 30, 380, 120); ctx.font = '24px sans-serif'; ctx.fillText(`SYNTHETIC SOURCE ${index + 1}`, 35, 220); return canvas.toDataURL().split(',')[1];
    }));
    const files = [{ name: 'same.png', mimeType: 'image/png', buffer: Buffer.from(pngs[0], 'base64') }, { name: 'remove.png', mimeType: 'image/png', buffer: Buffer.from(pngs[0], 'base64') }, { name: 'same.png', mimeType: 'image/png', buffer: Buffer.from(pngs[1], 'base64') }, { name: 'report.pdf', mimeType: 'application/pdf', buffer: pdf() }];
    stage = 'selection'; await page.locator('input[type=file]').setInputFiles(files); assert.equal(await page.locator('.selected-files li').count(), 4);
    await page.getByRole('button', { name: '移除第 2 个文件' }).click(); assert.equal(await page.locator('.selected-files li').count(), 3); checks.push('multi_file_removal');
    stage = 'upload_binding'; await page.getByRole('button', { name: '开始处理' }).click(); await page.locator('.result-view').waitFor();
    assert.deepEqual(batches[0].file_names, ['same.png', 'same.png', 'report.pdf']);
    const blobHash = () => page.locator('.source-preview img').evaluate(async image => [...new Uint8Array(await crypto.subtle.digest('SHA-256', await (await fetch(image.src)).arrayBuffer()))].map(x => x.toString(16).padStart(2, '0')).join(''));
    assert.equal(await blobHash(), crypto.createHash('sha256').update(files[0].buffer).digest('hex'));
    await page.locator('.task-row').nth(1).click(); await page.locator('.source-preview img').waitFor();
    assert.equal(await blobHash(), crypto.createHash('sha256').update(files[2].buffer).digest('hex'));
    await wait(() => document.querySelector('.source-preview img')?.naturalWidth === 440);
    await page.locator('.task-detail').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, 'image-desktop.png'), fullPage: true });
    checks.push('same_name_files_bound_by_response_task_ids_not_list_order');
    stage = 'pdf_page'; await page.locator('.task-row').filter({ hasText: 'report.pdf' }).click(); await page.locator('.source-preview object').waitFor();
    await page.getByRole('button', { name: '查看原件第 2 页' }).first().click(); assert.match(await page.locator('.source-preview object').getAttribute('data'), /#page=2/);
    assert.equal(await page.getByRole('spinbutton', { name: '原件页码' }).inputValue(), '2'); checks.push('pdf_source_page_request');
    stage = 'medical_filters'; await page.getByRole('searchbox', { name: '查找医疗项目' }).fill('wbc'); assert.equal(await page.locator('.medical-table tbody tr').count(), 1);
    await page.getByRole('searchbox', { name: '查找医疗项目' }).fill(''); await page.getByRole('combobox', { name: '筛选医疗项目' }).selectOption('unknown'); assert.match(await page.locator('.medical-table').innerText(), /合成阳性项/);
    await page.getByRole('combobox', { name: '筛选医疗项目' }).selectOption('abnormal'); assert.match(await page.locator('.medical-table').innerText(), /合成白细胞/);
    assert.equal(await page.locator('.medical-stats strong').allTextContents().then(x => x.every(v => v === '未确认')), true);
    await page.getByRole('combobox', { name: '筛选医疗项目' }).selectOption('all'); checks.push('medical_search_filter_preserves_unknown_stats');
    stage = 'screenshots'; await page.locator('.task-detail').scrollIntoViewIfNeeded();
    // Native PDF plugin paints asynchronously; page selection itself is a request, not a DOM-readable page assertion.
    await page.waitForTimeout(1800); await page.screenshot({ path: path.join(out, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(800); await page.screenshot({ path: path.join(out, 'mobile.png'), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); checks.push('desktop_mobile_synthetic_screenshots_no_overflow');
    await page.setViewportSize({ width: 1280, height: 900 });
    stage = 'rerun_notice'; await page.getByRole('button', { name: '重跑任务', exact: true }).click(); await page.getByText('已接收重跑请求，新执行正在排队。', { exact: true }).waitFor();
    const scrollCount = await page.evaluate(() => window.previewAudit.detailScrolls);
    await wait(() => !document.body.innerText.includes('已接收重跑请求，新执行正在排队。') && !!document.querySelector('.result-view'));
    assert.equal(await page.evaluate(() => window.previewAudit.detailScrolls), scrollCount); checks.push('rerun_notice_clears_without_poll_scroll');
    stage = 'cancel_notice'; const t = taskMap.get(batches[0].task_ids[2]); t.status = 'OCR'; t.cancel_requested = false; t.progress = 20;
    await page.getByRole('button', { name: '刷新批次', exact: true }).click(); await page.getByRole('button', { name: '取消任务', exact: true }).waitFor(); await page.getByRole('button', { name: '取消任务', exact: true }).click();
    await page.getByText('已请求取消；等待服务确认停止后才会显示“已取消”。', { exact: true }).waitFor();
    await wait(() => !document.body.innerText.includes('已请求取消；等待服务确认停止后才会显示“已取消”。') && document.querySelector('.task-row.selected')?.innerText.includes('已取消')); checks.push('cancel_waits_for_confirmation_and_clears_notice');
    stage = 'replace_and_fallback'; await page.locator('input[type=file]').setInputFiles({ name: 'unsupported.heic', mimeType: 'image/heic', buffer: Buffer.from('SYNTHETIC_UNDECODABLE_HEIC') }); await page.getByRole('button', { name: '开始处理' }).click();
    await page.getByText(/浏览器无法预览此原件/).waitFor(); assert.deepEqual(await page.evaluate(() => ({ active: window.previewAudit.active.length, revoked: window.previewAudit.revoked })), { active: 1, revoked: 3 }); checks.push('replacement_revokes_previous_batch_and_heic_fallback');
    stage = 'historical_preview'; await page.locator('.batch-row').nth(1).click(); await page.getByText(/没有此任务的本地原件/).waitFor(); checks.push('older_task_has_no_guessed_preview');
    stage = 'uncertain_upload'; failUpload = true; const before = uploadCount; await page.locator('input[type=file]').setInputFiles(files[0]); await page.getByRole('button', { name: '开始处理' }).click();
    await page.getByText(/上传结果暂无法确认/).waitFor(); assert.equal(await page.evaluate(() => window.previewAudit.active.length), 0); await page.waitForTimeout(2300); assert.equal(uploadCount, before + 1); checks.push('uncertain_upload_not_matched_or_automatically_repeated');
    stage = 'logout_cleanup'; failUpload = false; await page.getByRole('button', { name: '开始处理' }).click(); await page.locator('.source-preview img').waitFor();
    await page.getByRole('button', { name: '清除密钥并断开' }).click(); await page.locator('#api-key').waitFor(); assert.equal(await page.evaluate(() => window.previewAudit.active.length), 0); assert.equal(await page.locator('#api-key').inputValue(), ''); checks.push('logout_revokes_urls_and_key');
    assert.equal(errors.length, 0); checks.push('no_browser_page_errors'); report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.failure_stage = stage; report.failure_type = ['AssertionError', 'TimeoutError', 'Error'].includes(error?.name) ? error.name : 'BROWSER_ERROR';
    report.failure_code = 'SYNTHETIC_BROWSER_CHECK_FAILED'; process.exitCode = 1;
    if (page) await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true }).catch(() => {});
  } finally {
    await context?.close().catch(() => {}); await browser?.close().catch(() => {}); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    report.page_error_count = errors.length; report.upload_requests = uploadCount; report.finished_at = new Date().toISOString();
    report.dist_sha256 = fs.existsSync(path.join(dist, 'index.html')) ? crypto.createHash('sha256').update(fs.readFileSync(path.join(dist, 'index.html'))).digest('hex') : null;
    report.probe_sha256 = crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex');
    report.pdf_validation = 'Verified original blob URL, requested #page and page input; native PDF viewer final page is not independently asserted.';
    save(); process.stdout.write(JSON.stringify({ status: report.status, checks: checks.length, failure_stage: report.failure_stage ?? null, output: path.relative(root, out).replaceAll('\\', '/') }) + '\n');
  }
}
run().catch(() => { report.status = 'failed'; report.failure_code = 'PROBE_SETUP_FAILED'; save(); process.exitCode = 1; });
