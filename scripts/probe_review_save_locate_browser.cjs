// Real Vue / Element Plus review panels with synthetic inputs; never calls the business backend or OCR.
// node scripts/probe_review_save_locate_browser.cjs [new-output-directory] [--only-medical]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE_PATH || 'C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const outputRoot = path.join(root, 'output/review-save-locate');
fs.mkdirSync(outputRoot, { recursive: true });
const outputArg = process.argv.slice(2).find(arg => !arg.startsWith('--'));
const out = outputArg ? path.resolve(outputArg) : fs.mkdtempSync(path.join(outputRoot, 'attempt-'));
assert.ok(out.startsWith(path.join(root, 'output') + path.sep));
if (outputArg) fs.mkdirSync(out, { recursive: false });
const report = {checks:[], errors:[], business_requests:0, model_calls:0, source_hashes:{}};
for (const name of ['frontend/src/components/ReviewEditor.vue','frontend/src/components/TaskResultDrawer.vue','frontend/src/reveal.ts']) {
  report.source_hashes[name] = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex');
}
const onlyMedical = process.argv.includes('--only-medical');
let server, browser;
(async()=>{
  try {
    const {createServer} = await import(pathToFileURL(path.join(root, 'frontend/node_modules/vite/dist/node/index.js')).href);
    server = await createServer({root:path.join(root,'frontend'),logLevel:'error',server:{host:'127.0.0.1',port:0,hmr:false}});
    await server.listen(); const origin = server.resolvedUrls.local[0];
    const source = await (await fetch(origin+'src/components/ReviewEditor.vue')).text();
    const main = await (await fetch(origin+'src/main.ts')).text();
    const vue = source.match(/from\s+"([^"]*\/vue\.js[^"\s]*)"/)[1];
    const element = main.match(/from\s+"([^"]*\/element-plus\.js[^"\s]*)"/)[1];
    browser = await chromium.launch({executablePath:process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
    const page = await browser.newPage({viewport:{width:1500,height:1000}});
    await page.addInitScript(()=>{
      window.__scrollCalls=[];
      const scroll=Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView=function(options){
        const root=document.getElementById('review-scroll')||document.querySelector('.el-drawer__body');
        if(root&&this.id?.startsWith('rev-'))window.__scrollCalls.push({id:this.id,
          scrollHeight:root.scrollHeight,clientHeight:root.clientHeight,scrollTop:root.scrollTop,
          targetTop:this.getBoundingClientRect().top,wrapHeight:this.closest('.el-collapse-item__wrap')?.style.maxHeight,
          behavior:options?.behavior,time:performance.now(),
          runningAnimations:this.closest('.el-collapse-item__wrap')?.getAnimations().filter(a=>a.playState==='running').length??0});
        return scroll.call(this,options);
      };
    });
    page.on('pageerror',error=>report.errors.push(error.message));
    await page.route('**/api/**',route=>{report.business_requests++;return route.abort()});
    await page.route('**/__fixture*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`
      <style>#review-scroll{height:650px;overflow:auto;border:1px solid #ddd;padding:20px;max-width:1100px;margin:30px auto}</style>
      <div id="app"></div><script type="module">
      import {createApp,h,ref} from '${vue}'; import ElementPlus from '${element}';
      import Editor from '/src/components/ReviewEditor.vue'; import Drawer from '/src/components/TaskResultDrawer.vue';
      import '/src/style.css'; import '/node_modules/element-plus/dist/index.css';
      const id='11111111-2222-4333-8444-555555555555';
      const field=(i)=>({key:'field'+i,label:'测试字段'+i,value:'原始值'+i,confidence:null,confidence_method:'unavailable',need_review:false,review_issues:[]});
      const result={task_id:id,run_id:id,result_revision:1,status:'NEED_REVIEW',doc_type:'MEDICAL_REPORT',
        fields:Array.from({length:20},(_,i)=>field(i)),review_issues:[],
        items:Array.from({length:30},(_,i)=>({item_id:'item'+i,name:'测试项目'+i,result_raw:'1',unit:'',
          reference_range:'',reported_abnormal_marker:null,risk_grade:'A',diagnosis:'',abnormal_flag:'NORMAL',
          abnormal_basis:'report_grade',need_review:false,review_issues:[],confidence:null,confidence_method:'unavailable'})),
        report_summary:{declared_count:1,scope:'follow_up_required',findings:[{finding_id:'finding1',text:'建议复查',sources:[],review_issues:[]}]},
        stats:{total:30,normal:30,abnormal:0,unknown:0,categories:[]},abnormal_summary:[],limitations:[]};
      const state=window.fixture={result,saves:[],dirty:false,reviewCalls:0};
      const drawer=new URL(location.href).searchParams.has('drawer');
      if(drawer){if(new URL(location.href).searchParams.get('drawer')!=='medical'){
          result.doc_type='DIPLOMA';result.items=[];delete result.report_summary;}
        const task={task_id:id,run_id:id,result_revision:1,status:'NEED_REVIEW',doc_type:result.doc_type,
          cancel_requested:false,file_name:'合成材料.jpg',page_count:0,actual_source_page_count:22,pages:[]};
        const api={result:async()=>result,review:async()=>{state.reviewCalls++;throw new Error('synthetic network failure')}};
        createApp({render:()=>h(Drawer,{open:true,task,api,monitor:{start(){}},previews:{get(){}},canWrite:true,catalogue:[]})}).use(ElementPlus).mount('#app');
      }else {
        const focus=ref(null);let seq=0;
        state.jump=(kind,id)=>focus.value={kind,id,seq:++seq};
        const app=createApp({render:()=>h('div',{id:'review-scroll'},[h(Editor,{result,canWrite:true,busy:false,pageCount:22,focus:focus.value,
          onSave:body=>state.saves.push(body),onDirty:value=>state.dirty=value})])}).use(ElementPlus);
        state.close=()=>app.unmount();app.mount('#app');
      }
      </script>`}));
    const measure = async(id,scroller='#review-scroll')=>page.evaluate(({id,scroller})=>{
      const el=document.getElementById(id),root=document.querySelector(scroller),r=el.getBoundingClientRect(),v=root.getBoundingClientRect();
      return {targetTop:r.top,targetBottom:r.bottom,viewportTop:v.top,viewportBottom:v.bottom,
        visible:Math.max(0,Math.min(r.bottom,v.bottom)-Math.max(r.top,v.top)),
        active:document.activeElement?.id,scrollTop:root.scrollTop,scrollHeight:root.scrollHeight};
    },{id,scroller});
    // Long-distance smooth scrolling can take more than a second; test arrival, not a guessed duration.
    const visible = (id,scroller='#review-scroll')=>page.waitForFunction(({id,scroller})=>{
      const el=document.getElementById(id),root=document.querySelector(scroller);
      if(!el||!root)return false;
      const r=el.getBoundingClientRect(),v=root.getBoundingClientRect();
      return r.height>0&&r.top>=v.top-2&&r.bottom<=v.bottom+2;
    },{id,scroller},{timeout:5000});
    const check = async(name,fn)=>{
      const entry={name};
      try{await fn(entry);entry.passed=true}catch(error){entry.passed=false;entry.failure=String(error.message)}
      report.checks.push(entry);console.log(JSON.stringify(entry));
    };
    for(const reducedMotion of onlyMedical?[]:['no-preference','reduce']){
      await check('invalid added row reaches actual DOM after reopening a long panel ('+reducedMotion+')',async entry=>{
        await page.emulateMedia({reducedMotion});await page.goto(origin+'__fixture');
        const header=page.locator('.el-collapse-item__header').filter({hasText:'编辑检测项目 / 增删项目'});
        await header.click();await page.getByRole('button',{name:'新增检测项目',exact:true}).click();
        await page.locator('#rev-added-0 input').first().fill('保留新增草稿');
        await header.click();await page.locator('#rev-added-0').waitFor({state:'hidden'});
        await page.getByRole('button',{name:'保存修正并重新校验',exact:true}).click();
        await visible('rev-added-0');
        entry.measurement=await measure('rev-added-0');
        entry.scrollCalls=await page.evaluate(()=>window.__scrollCalls);
        entry.saveCount=await page.evaluate(()=>window.fixture.saves.length);
        entry.draft=await page.locator('#rev-added-0 input').first().inputValue();
        await page.screenshot({path:path.join(out,'invalid-added-'+reducedMotion+'.png')});
        assert.equal(entry.saveCount,0);assert.equal(entry.draft,'保留新增草稿');
        assert.equal(entry.scrollCalls.length,1);
        assert.equal(entry.scrollCalls[0].behavior,reducedMotion==='reduce'?'instant':'smooth');
        assert.equal(entry.scrollCalls[0].runningAnimations,0);
        assert.equal(entry.measurement.active,'rev-added-0');
        assert.ok(entry.measurement.visible>0,'offending row remains outside the scroll viewport');
      });
    }
    if(!onlyMedical)await check('summary rejection opens its real panel and preserves edits',async entry=>{
      await page.emulateMedia({reducedMotion:'no-preference'});await page.goto(origin+'__fixture');
      await page.locator('.el-collapse-item__header').filter({hasText:'编辑报告检查治疗清单'}).click();
      await page.locator('#rev-finding-finding1 .el-checkbox').click();
      await page.getByRole('button',{name:'保存修正并重新校验',exact:true}).click();await page.waitForTimeout(900);
      entry.measurement=await measure('rev-summary');
      assert.equal(await page.locator('#rev-summary .el-collapse-item__header').getAttribute('aria-expanded'),'true');
      assert.ok(entry.measurement.visible>0);assert.equal(await page.evaluate(()=>window.fixture.saves.length),0);
      await page.screenshot({path:path.join(out,'summary-error.png')});
    });
    if(!onlyMedical)await check('valid local save emits the edited field once with its original revision',async entry=>{
      await page.goto(origin+'__fixture');
      await page.locator('#rev-field-field0 input').fill('保留有效修正');
      await page.getByRole('button',{name:'保存修正并重新校验',exact:true}).click();
      entry.saves=await page.evaluate(()=>window.fixture.saves);
      assert.equal(entry.saves.length,1);assert.equal(entry.saves[0].fields.field0,'保留有效修正');
      assert.equal(entry.saves[0].expected_revision,1);
    });
    if(!onlyMedical)await check('server save failure brings the drawer alert into view and preserves the field draft',async entry=>{
      await page.goto(origin+'__fixture?drawer=1');
      const field=page.locator('#rev-field-field0 input');await field.fill('保留未提交草稿');
      await page.getByRole('button',{name:'保存修正并重新校验',exact:true}).click();
      await page.locator('#drawer-review-error').waitFor();await page.waitForTimeout(900);
      entry.measurement=await measure('drawer-review-error','.el-drawer__body');
      assert.ok(entry.measurement.visible>0);assert.equal(await field.inputValue(),'保留未提交草稿');
      assert.equal(await page.evaluate(()=>window.fixture.reviewCalls),1);
      assert.ok((await page.locator('#drawer-review-error').innerText()).includes('草稿已保留'));
      await page.screenshot({path:path.join(out,'server-save-error.png')});
    });
    await check('actual medical drawer reaches the invalid row after reopening its long editor panel',async entry=>{
      await page.emulateMedia({reducedMotion:'no-preference'});await page.goto(origin+'__fixture?drawer=medical');
      const header=page.locator('.el-collapse-item__header').filter({hasText:'编辑检测项目 / 增删项目'});
      await header.click();await page.getByRole('button',{name:'新增检测项目',exact:true}).click();
      await page.locator('#rev-added-0 input').first().fill('保留实际抽屉草稿');
      await header.click();await page.locator('#rev-added-0').waitFor({state:'hidden'});
      await page.getByRole('button',{name:'保存修正并重新校验',exact:true}).click();await visible('rev-added-0','.el-drawer__body');
      entry.measurement=await measure('rev-added-0','.el-drawer__body');
      entry.scrollCalls=await page.evaluate(()=>window.__scrollCalls);
      entry.reviewCalls=await page.evaluate(()=>window.fixture.reviewCalls);
      entry.draft=await page.locator('#rev-added-0 input').first().inputValue();
      await page.screenshot({path:path.join(out,'medical-drawer-invalid-added.png')});
      assert.equal(entry.reviewCalls,0);assert.equal(entry.draft,'保留实际抽屉草稿');
      assert.equal(entry.scrollCalls.length,1);
      assert.equal(entry.measurement.active,'rev-added-0');
      assert.ok(entry.measurement.visible>0,'invalid row is outside the actual drawer scroll viewport');
    });
    if(!onlyMedical)await check('issue jump waits for the same long panel before scrolling',async entry=>{
      await page.goto(origin+'__fixture');
      await page.evaluate(()=>window.fixture.jump('item','item29'));
      await visible('rev-item-item29');
      entry.measurement=await measure('rev-item-item29');
      entry.scrollCalls=await page.evaluate(()=>window.__scrollCalls);
      assert.equal(entry.scrollCalls.length,1);assert.equal(entry.scrollCalls[0].id,'rev-item-item29');
      assert.equal(entry.scrollCalls[0].runningAnimations,0);
    });
    for(const action of onlyMedical?[]:['newer-jump','unmount'])await check(action+' cancels an expanding panel reveal',async entry=>{
      await page.goto(origin+'__fixture');
      await page.evaluate(()=>window.fixture.jump('item','item29'));
      await page.waitForFunction(()=>document.querySelector('.el-collapse-item__header')?.getAttribute('aria-expanded')==='true');
      if(action==='newer-jump'){
        await page.evaluate(()=>window.fixture.jump('field','field0'));await visible('rev-field-field0');
      }else await page.evaluate(()=>window.fixture.close());
      await page.waitForTimeout(500);
      entry.scrollCalls=await page.evaluate(()=>window.__scrollCalls);
      assert.ok(!entry.scrollCalls.some(call=>call.id==='rev-item-item29'));
      assert.equal(entry.scrollCalls.length,action==='unmount'?0:1);
      if(action==='newer-jump')assert.equal(await page.evaluate(()=>document.activeElement.id),'rev-field-field0');
    });
    report.passed=report.checks.every(check=>check.passed)&&report.errors.length===0&&report.business_requests===0;
    if(!report.passed)process.exitCode=1;
  }catch(error){report.failure=String(error.stack);report.passed=false;process.exitCode=1}
  finally{
    if(browser)await browser.close();if(server)await server.close();
    fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({passed:report.passed,checks:report.checks.length,output:out,errors:report.errors}));
  }
})();
