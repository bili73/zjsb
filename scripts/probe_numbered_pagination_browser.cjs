// Isolated actual Vue panels with synthetic accounts/tasks; no business service access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const base = path.join(root, 'output/numbered-pagination'); fs.mkdirSync(base, {recursive:true});
const out = fs.mkdtempSync(path.join(base, 'attempt-'));
const report = {status:'running', checks:[], errors:[], business_requests:0};
let browser, server;
(async () => {
  try {
    const {createServer} = await import(pathToFileURL(path.join(root,'frontend/node_modules/vite/dist/node/index.js')).href);
    server = await createServer({root:path.join(root,'frontend'),logLevel:'error',server:{host:'127.0.0.1',port:0,hmr:false}});
    await server.listen(); const origin=server.resolvedUrls.local[0];
    const component=await (await fetch(origin+'src/components/AccountManagement.vue')).text();
    const main=await (await fetch(origin+'src/main.ts')).text();
    const vue=component.match(/from\s+"([^"]*\/vue\.js[^"\s]*)"/)[1];
    const element=main.match(/from\s+"([^"]*\/element-plus\.js[^"\s]*)"/)[1];
    browser=await chromium.launch({executablePath:process.env.EDGE_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror',error=>report.errors.push(error.message));
    await page.route('**/api/**',route=>{report.business_requests++;return route.abort()});
    await page.route('**/__fixture*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`
      <div id="app" style="padding:24px"></div><script type="module">
      import {createApp,h} from '${vue}'; import ElementPlus from '${element}';
      import Accounts from '/src/components/AccountManagement.vue'; import Batches from '/src/components/BatchBoard.vue';
      import {createMonitor} from '/src/monitor.ts'; import {BusinessApi} from '/src/api.ts';
      import '/src/style.css'; import '/node_modules/element-plus/dist/index.css';
      const id=i=>'00000000-0000-4000-8000-'+String(i).padStart(12,'0');
      const users=Array.from({length:52},(_,i)=>({user_id:id(i),username:'user_'+String(i).padStart(2,'0'),display_name:'测试账号'+i,role:i===0?'admin':'operator',enabled:true}));
      const batches=Array.from({length:55},(_,i)=>({batch_id:id(i+100),display_name:'合成批次'+i,status:'COMPLETED',file_count:1,created_at:new Date().toISOString()}));
      const f=window.fixture={calls:[],users,batches};
      const api=new BusinessApi(async input=>{
        const url=new URL(input,location.origin);
        if(url.pathname==='/api/v1/batches'){
          const page=Number(url.searchParams.get('page')),page_size=Number(url.searchParams.get('page_size'));
          f.calls.push({page,page_size});return Response.json({items:batches.slice((page-1)*page_size,page*page_size),total:batches.length,page,page_size});
        }
        const bid=url.pathname.split('/batches/')[1]?.split('/')[0];
        if(url.pathname.endsWith('/tasks'))return Response.json([{task_id:id(Number(bid.slice(-12))+200),batch_id:bid,run_id:id(500),result_revision:1,cancel_requested:false,status:'COMPLETED',doc_type:'DIPLOMA',file_name:'synthetic.png',page_count:1,pages:[]}]);
        return Response.json(batches.find(b=>b.batch_id===bid));
      });
      const monitor=createMonitor(()=>api,{isVisible:()=>true});f.monitor=monitor;
      const accounts=new URLSearchParams(location.search).get('view')==='accounts';
      const accountApi={users:async()=>[...users]};
      createApp({setup:()=>()=>accounts?h(Accounts,{api:accountApi,currentUser:users[0]}):h(Batches,{api,monitor,canWrite:false,isAdmin:false,uploadReset:0,catalogue:[],active:false})}).use(ElementPlus).mount('#app');
      </script>`}));
    await page.goto(origin+'__fixture?view=accounts');
    await page.locator('.el-table__body').getByText('user_01',{exact:true}).waitFor();
    await page.locator('.el-pager .number').filter({hasText:/^3$/}).click();
    await page.locator('.el-table__body').getByText('user_40',{exact:true}).waitFor();
    assert.equal(await page.locator('.el-table__body .el-table__row').count(),12);
    await page.locator('.el-pagination__sizes .el-select').click();
    await page.getByRole('option').filter({hasText:'50/page'}).click();
    await page.locator('.el-table__body').getByText('user_01',{exact:true}).waitFor();
    assert.equal(await page.locator('.el-table__body .el-table__row').count(),50);
    report.checks.push('account direct numeric pages and size reset to page one');
    await page.locator('.el-pager .number').filter({hasText:/^2$/}).click();
    await page.evaluate(()=>window.fixture.users.splice(50));
    await page.getByRole('button',{name:'刷新列表',exact:true}).click();
    await page.locator('.el-table__body').getByText('user_01',{exact:true}).waitFor();
    assert.equal(await page.locator('.el-pager .number').count(),1);
    report.checks.push('account list shrink clamps to the last valid page');
    await page.locator('.el-pagination__sizes .el-select').click();
    await page.getByRole('option').filter({hasText:'20/page'}).click();
    await page.locator('.el-pagination').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'accounts.png')});
    await page.goto(origin+'__fixture?view=batches');
    await page.getByText('合成批次0',{exact:true}).waitFor();
    await page.waitForFunction(()=>!window.fixture.monitor.state.polling);
    await page.locator('.el-pager .number').filter({hasText:/^2$/}).click();
    await page.getByText('合成批次50',{exact:true}).waitFor();
    assert.equal(await page.getByText('合成批次0',{exact:true}).count(),0);
    assert.deepEqual(await page.evaluate(()=>window.fixture.calls.map(c=>c.page)),[1,2]);
    assert.equal(await page.locator('.el-collapse-item').count(),5);
    report.checks.push('batch direct numeric page shows only that page with one list request');
    await page.locator('.el-pagination__sizes .el-select').click();
    await page.getByRole('option').filter({hasText:'20/page'}).click();
    await page.getByText('合成批次0',{exact:true}).waitFor();
    assert.equal(await page.locator('.el-collapse-item').count(),20);
    assert.equal(await page.evaluate(()=>window.fixture.monitor.state.page),1);
    report.checks.push('batch page size resets to page one');
    await page.locator('.el-pagination').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'batches.png')});
    assert.equal(report.business_requests,0);assert.deepEqual(report.errors,[]);report.status='passed';
  } catch(error) {report.status='failed';report.failure=String(error.stack);process.exitCode=1;}
  finally {if(browser)await browser.close();if(server)await server.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({status:report.status,checks:report.checks.length,output:out,failure:report.failure}));}
})();
