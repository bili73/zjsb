// Actual Vue components on synthetic HTTP/localhost origins; no production login or model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const base = path.join(root, 'output/http-browser-capabilities');
fs.mkdirSync(base, { recursive: true });
const out = fs.mkdtempSync(path.join(base, 'attempt-'));
const report = { status: 'running', checks: [], errors: [], business_requests: 0 };
let server, browser;
(async () => {
  try {
    const { createServer } = await import(pathToFileURL(path.join(root, 'frontend/node_modules/vite/dist/node/index.js')).href);
    server = await createServer({ root: path.join(root, 'frontend'), logLevel: 'error', server: { host: '127.0.0.1', port: 0, hmr: false } });
    await server.listen(); const origin = server.resolvedUrls.local[0];
    const component = await (await fetch(origin + 'src/components/RegionOcrDialog.vue')).text();
    const main = await (await fetch(origin + 'src/main.ts')).text();
    const vue = component.match(/from\s+"([^"]*\/vue\.js[^"\s]*)"/)[1];
    const element = main.match(/from\s+"([^"]*\/element-plus\.js[^"\s]*)"/)[1];
    browser = await chromium.launch({ executablePath: process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
    async function open(http, cinema, diagnostics = false, denied = false) {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      page.on('pageerror', e => report.errors.push(e.message));
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.pathname.startsWith('/api/')) { report.business_requests++; return route.abort(); }
        if (url.pathname === '/__fixture') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `
          <div id="app"></div><script type="module">
          import {createApp,ref,h} from '${vue}'; import ElementPlus from '${element}';
          import Region from '/src/components/RegionOcrDialog.vue'; import Diagnostics from '/src/components/DiagnosticsPanel.vue';
          import {recordDiagnostic} from '/src/diagnostics.ts'; import {LocalPreviewBatch} from '/src/workbench.ts';
          import '/src/style.css'; import '/node_modules/element-plus/dist/index.css';
          ${denied ? "Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>Promise.reject(new Error('denied'))}});" : ''}
          const text='00123\\n合成文字 2024年6月', opened=ref(true), task={task_id:'11111111-2222-4333-8444-555555555555',run_id:'66666666-7777-4888-9999-000000000000',result_revision:1,page_count:1,doc_type:'DIPLOMA'};
          window.fixture={opened,text};
          const api={preview:async()=>({blob:new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500"><rect width="800" height="500" fill="white"/><text x="30" y="80">SYNTHETIC 00123</text></svg>'],{type:'image/svg+xml'}),corrected:true}),ocrRegion:async()=>({text,confidence:.9}),diagnosticEvents:async()=>({items:[],next_cursor:null,incomplete:false,skipped_files:0,skipped_records:0})};
          window.probeCrypto=async()=>{
            const card=recordDiagnostic({origin:'window',operation:'interface',code:'CLIENT_ERROR',error:new TypeError('PRIVATE')});
            const cache=new LocalPreviewBatch(5,()=> 'blob:synthetic',()=>{});
            const matched=await cache.addMatched([new File(['abc'],'sample.png')],[{...task,content_hash:'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}]);
            const result={id:card.error_id,matched,preview:!!cache.get(task.task_id),privateValue:JSON.stringify(card).includes('PRIVATE')};cache.clear();return result;
          };
          recordDiagnostic({origin:'window',operation:'interface',code:'CLIENT_ERROR'});
          createApp({setup:()=>()=>${diagnostics ? "h(Diagnostics,{open:opened.value,api,isAdmin:true,'onUpdate:open':v=>opened.value=v})" : `h(Region,{open:opened.value,api,task,initialPage:1,canWrite:true,cinema:${cinema},onCancel:()=>opened.value=false})`}}).use(ElementPlus).mount('#app');
          </script>` });
        const response = await fetch(origin + url.pathname.slice(1) + url.search);
        await route.fulfill({ status: response.status, contentType: response.headers.get('content-type') || 'text/plain', body: Buffer.from(await response.arrayBuffer()) });
      });
      await page.goto((http ? 'http://ocr-http.test/' : origin) + '__fixture');
      return page;
    }
    async function paste(page, parent) {
      await parent.evaluate(el => { let field=el.querySelector('#fixture-paste'); if(!field){field=document.createElement('textarea');field.id='fixture-paste';el.appendChild(field);} field.value=''; });
      await page.locator('#fixture-paste').click(); await page.keyboard.press('Control+V');
      return page.locator('#fixture-paste').inputValue();
    }
    for (const http of [true, false]) for (const cinema of [false, true]) {
      const page = await open(http, cinema);
      try {
        await page.locator('.region-stage img').waitFor();
        await page.waitForFunction(() => document.querySelector('.region-stage img')?.naturalWidth > 0);
        const box = await page.locator('.region-stage img').boundingBox();
        await page.mouse.move(box.x+box.width*.1,box.y+box.height*.1); await page.mouse.down();
        await page.mouse.move(box.x+box.width*.65,box.y+box.height*.3); await page.mouse.up();
        await page.getByRole('button',{name:'识别选区',exact:true}).click();
        const panel=page.getByRole('dialog',{name:'选区识别结果',exact:true});
        const edited='00124\n人工核对文字 2024年6月';
        await page.getByRole('textbox',{name:'选区识别文字，可修改或复制',exact:true}).fill(edited);
        await panel.getByRole('button',{name:'复制文字',exact:true}).click();
        await panel.getByRole('button',{name:'已复制',exact:true}).waitFor();
        assert.equal(await paste(page,panel),edited);
        await panel.getByRole('button',{name:'复制日期',exact:true}).click();
        assert.equal(await paste(page,panel),'2024-06');
        assert.equal(await page.getByRole('textbox',{name:'选区识别文字，可修改或复制',exact:true}).inputValue(),edited);
        if (http && !cinema) {
          await page.evaluate(()=>{document.execCommand=()=>false;});
          await panel.locator('.date-suggestion button').click();
          await page.getByText('自动复制未成功，请选中文字，使用 Ctrl+C（Mac 为 ⌘C）复制。',{exact:true}).waitFor();
          assert.deepEqual(await page.evaluate(()=>({value:document.activeElement.value,start:document.activeElement.selectionStart,end:document.activeElement.selectionEnd})),{value:'2024-06',start:0,end:7});
        }
        const cryptoCheck=await page.evaluate(()=>window.probeCrypto());
        assert.match(cryptoCheck.id,/^[a-f0-9-]{36}$/);assert.equal(cryptoCheck.matched,true);assert.equal(cryptoCheck.preview,true);assert.equal(cryptoCheck.privateValue,false);
        report.checks.push({http,cinema,copy_text:true,copy_date:true,crypto:cryptoCheck});
        await page.screenshot({path:path.join(out,`region-${http?'http':'localhost'}-${cinema?'cinema':'dialog'}.png`)});
      } finally { await page.close(); }
    }
    for (const denied of [false,true]) {
      const page=await open(true,false,true,denied);
      try {
        await page.getByRole('button',{name:'复制',exact:true}).click();
        await page.getByText('诊断信息已复制。',{exact:true}).waitFor();
        const drawer=page.getByRole('dialog',{name:'诊断信息',exact:true});
        const value=JSON.parse(await paste(page,drawer));assert.equal(value.code,'CLIENT_ERROR');
        await page.locator('.filters .el-select').click();
        const options=await page.getByRole('option').allTextContents();
        assert.deepEqual(options,['ERROR（错误）','CRITICAL（严重故障）']);
        report.checks.push({diagnostic_copy:true,modern_denied:denied,levels:options});
      } finally { await page.close(); }
    }
    assert.equal(report.business_requests,0);assert.deepEqual(report.errors,[]);report.status='passed';
  } catch(error) { report.status='failed';report.failure=String(error.stack);process.exitCode=1; }
  finally { if(browser)await browser.close();if(server)await server.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks.length,output:out,failure:report.failure})); }
})();
