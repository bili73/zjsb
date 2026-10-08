// Only synthetic material is displayed or captured. Credentials arrive over stdin.
const { chromium } = require('C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const args = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  const checks = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', () => errors.push('pageerror'));
    await page.goto(args.url);
    await page.locator('#api-key').fill('wrong-key-for-controlled-test');
    await page.getByRole('button', { name: '验证并连接' }).click();
    await page.locator('.business-notice.error').waitFor();
    const downloaded = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载错误卡片 JSON' }).first().click();
    const download = await downloaded;
    const destination = path.join(args.output, 'frontend-error.json');
    await download.saveAs(destination);
    const card = JSON.parse(fs.readFileSync(destination, 'utf8'));
    if (card.code !== 'UNAUTHORIZED' || JSON.stringify(card).includes(args.key)) throw Error('UNSAFE_ERROR_CARD');
    checks.push('auth_failure_diagnostic');
    await page.locator('#api-key').fill(args.key);
    await page.getByRole('button', { name: '验证并连接' }).click();
    await page.locator('.upload-form').waitFor();
    await page.locator('.upload-form select').selectOption('DIPLOMA');
    await page.locator('input[type=file]').setInputFiles(args.file);
    const accepted = page.waitForResponse(response => response.url().endsWith('/api/v1/batches') && response.request().method() === 'POST');
    await page.getByRole('button', { name: '开始处理' }).click();
    if ((await accepted).status() !== 202) throw Error('UPLOAD_NOT_ACCEPTED');
    await page.locator('.result-view').filter({ hasText: '测试样本' }).waitFor({ timeout: 40000 });
    if (!(await page.locator('.result-view').innerText()).includes('测试样本')) throw Error('MISSING_SYNTHETIC_RESULT');
    checks.push('upload_pdf_readonly_result');
    await page.screenshot({ path: path.join(args.output, 'workspace-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(args.output, 'workspace-mobile.png'), fullPage: true });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('MOBILE_OVERFLOW');
    checks.push('mobile_layout');
    await page.getByRole('button', { name: '引擎状态', exact: true }).click();
    await page.screenshot({ path: path.join(args.output, 'engines.png'), fullPage: true });
    if (errors.length) throw Error('PAGE_ERROR');
    checks.push('no_page_errors');
    process.stdout.write(JSON.stringify({ status: 'passed', checks }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ status: 'failed', checks, failure_type: error.constructor.name,
      failure_code: ['UNSAFE_ERROR_CARD','MISSING_SYNTHETIC_RESULT','MOBILE_OVERFLOW','PAGE_ERROR','UPLOAD_NOT_ACCEPTED'].includes(error.message) ? error.message : 'BROWSER_ASSERTION_FAILED' }));
    process.exitCode = 1;
  } finally { await browser.close(); }
})();
