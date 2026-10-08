// Actual API admission in Edge. Credentials and synthetic buffers arrive over stdin.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const messages = {
  UNSUPPORTED_FORMAT: '暂不支持此图片编码或多帧材料；请另存为单张 JPG/PNG，或将多页转换为 PDF。',
  DECODE_FAILED: '文件无法解码，请重新导出图片或使用未加密的 PDF。',
};
const safeId = value => typeof value === 'string' && (/^[a-f\d]{8}-(?:[a-f\d]{4}-){3}[a-f\d]{12}$/i.test(value) || /^e_[A-Za-z\d]{1,80}$/.test(value));
(async () => {
  const args = JSON.parse(fs.readFileSync(0, 'utf8'));
  let browser, page, stage = 'browser_start';
  const report = { status: 'failed', checks: [] };
  const errors = [];
  try {
    browser = await chromium.launch({ executablePath: process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
    page = await context.newPage();
    page.on('pageerror', () => errors.push('PAGE_ERROR'));
    let posts = 0;
    page.on('request', request => { if (new URL(request.url()).pathname === '/api/v1/batches' && request.method() === 'POST') posts++; });
    stage = 'auth';
    await page.goto(args.url);
    await page.locator('#api-key').fill(args.key);
    await page.getByRole('button', { name: '验证并连接' }).click();
    await page.locator('.upload-form').waitFor();
    // Only synthetic account/material labels can appear in screenshots.
    assert.equal(await page.locator('#api-key').count(), 0);
    await page.locator('.upload-form select').selectOption('DIPLOMA');
    await page.locator('input[type=file]').setInputFiles(args.files.map(file => ({ name: file.name, mimeType: file.mime, buffer: Buffer.from(file.base64, 'base64') })));
    stage = 'upload';
    const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/batches' && response.request().method() === 'POST');
    await page.getByRole('button', { name: '开始处理' }).click();
    const response = await pending;
    report.http_status = response.status();
    assert.equal(response.status(), args.expected_status);
    assert.ok(safeId(response.headers()['x-request-id']));
    const body = await response.json();
    report.checks.push('real_multipart_status_and_request_id');
    if (args.expected_status === 202) {
      assert.ok(safeId(body.batch_id));
      assert.equal(body.task_ids.length, args.files.length);
      assert.ok(body.task_ids.every(safeId));
      await page.locator('.task-row').first().waitFor();
      assert.match(await page.locator('.task-row').first().innerText(), /排队中/);
      const tasks = await context.request.get(`${args.url}/api/v1/batches/${body.batch_id}/tasks`, { headers: { 'X-API-Key': args.key } });
      assert.equal(tasks.status(), 200);
      const rows = await tasks.json();
      assert.equal(rows.length, args.files.length);
      assert.ok(rows.every(task => task.status === 'QUEUED'));
      report.checks.push('accepted_tasks_remain_queued_without_ocr');
    } else {
      assert.equal(body.code, args.expected_code);
      assert.ok(safeId(body.error_id));
      assert.equal(body.request_id, response.headers()['x-request-id']);
      report.error_code = body.code;
      report.error_id = body.error_id;
      const notice = page.locator('.business-main > .business-notice.error');
      await notice.waitFor();
      assert.equal(await notice.locator('strong').innerText(), messages[args.expected_code]);
      assert.ok((await notice.innerText()).includes(body.error_id));
      assert.equal(await page.locator('.selected-files li').count(), args.files.length);
      const pendingDownload = page.waitForEvent('download');
      await page.getByRole('button', { name: '下载错误卡片 JSON' }).first().click();
      const download = await pendingDownload;
      const stream = await download.createReadStream();
      const chunks = []; for await (const chunk of stream) chunks.push(chunk);
      const text = Buffer.concat(chunks).toString('utf8');
      const card = JSON.parse(text);
      assert.equal(card.code, args.expected_code);
      assert.equal(card.http_status, args.expected_status);
      assert.equal(card.error_id, body.error_id);
      assert.ok(!text.includes(args.key) && !text.includes(args.url));
      assert.ok(!args.files.some(file => text.includes(file.name)));
      const allowed = new Set(['schema_version', 'error_id', 'request_id', 'occurred_at', 'app_version', 'origin', 'operation', 'code', 'http_status', 'stage', 'exception_type', 'stack_frames']);
      assert.ok(Object.keys(card).every(key => allowed.has(key)));
      fs.writeFileSync(path.join(args.output, `${args.case_id}-diagnostic.json`), JSON.stringify(card, null, 2));
      report.checks.push('actionable_static_message_and_safe_diagnostic');
    }
    stage = 'no_retry';
    await page.waitForTimeout(2400);
    assert.equal(posts, 1);
    report.post_count = posts;
    report.checks.push('single_post_no_automatic_retry');
    stage = 'screenshots';
    await page.screenshot({ path: path.join(args.output, `${args.case_id}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(args.output, `${args.case_id}-mobile.png`), fullPage: true });
    assert.equal(errors.length, 0);
    report.checks.push('synthetic_screenshots_no_mobile_overflow_or_page_errors');
    report.status = 'passed';
  } catch {
    report.failure_stage = stage;
    report.failure_code = 'BROWSER_ASSERTION_FAILED';
    process.exitCode = 1;
    // No screenshot before auth: never capture a key input after a failed transition.
    if (page && !['browser_start', 'auth'].includes(stage)) {
      await page.screenshot({ path: path.join(args.output, `${args.case_id}-failure.png`), fullPage: true }).catch(() => {});
    }
  } finally {
    await browser?.close();
    report.browser_closed = true;
    process.stdout.write(JSON.stringify(report));
  }
})();
