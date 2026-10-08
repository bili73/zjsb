import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const data=JSON.parse(await fs.readFile(path.join(root,'output/paddle-ablation-20260929/data/benchmark.json'),'utf8'));
const out=path.join(root,'outputs/01a0e741-2881-71e0-9d30-b7b4caecde0a');
await fs.mkdir(out,{recursive:true});
const wb=Workbook.create();
const main=wb.worksheets.add('方案对照');
const detail=wb.worksheets.add('区域实测');
const fields=wb.worksheets.add('字段核对');
const col=i=>{let s='';for(let n=i+1;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
function style(sheet,range){
  sheet.showGridLines=false;
  const r=sheet.getRange(range);
  r.format.font={name:'Arial',size:10,color:'#172B4D'};
  r.format.columnWidth=18;r.format.rowHeight=24;r.format.verticalAlignment='center';
}
function header(sheet,range){
  const r=sheet.getRange(range);r.format.fill='#243B53';
  r.format.font={name:'Arial',size:10,bold:true,color:'#FFFFFF'};
  r.format.horizontalAlignment='center';r.format.wrapText=true;r.format.rowHeight=44;
}
function raw(sheet,rows,name){
  const keys=Object.keys(rows[0]),end=rows.length+1,range=`A1:${col(keys.length-1)}${end}`;
  style(sheet,range);sheet.getRange(range).setNumberFormat('@');
  const display=v=>typeof v==='string'&&/^\d{12,}$/.test(v)?v.match(/.{1,4}/g).join(' '):v??null;
  sheet.getRange(range).values=[keys,...rows.map(r=>keys.map(k=>typeof r[k]==='object'&&r[k]!==null?JSON.stringify(r[k]):display(r[k])))];
  sheet.tables.add(range,true,name);header(sheet,`A1:${col(keys.length-1)}1`);
  keys.forEach((k,i)=>{
    const r=sheet.getRange(`${col(i)}2:${col(i)}${end}`);
    if(rows.some(x=>typeof x[k]==='number'))r.setNumberFormat(/accuracy|rate/.test(k)?'0.0%':/seconds|_s$|gib/.test(k)?'0.000':'0');
    if(/id|value|file|notes/.test(k))sheet.getRange(`${col(i)}1:${col(i)}${end}`).format.columnWidth=35;
    if(/region_name|normalization/.test(k))sheet.getRange(`${col(i)}1:${col(i)}${end}`).format.columnWidth=58;
  });
  sheet.freezePanes.freezeRows(1);return keys;
}
const rk=raw(detail,data.runs,'AblationRegions');
const fk=raw(fields,data.checks,'AblationFields');
const rc=k=>col(rk.indexOf(k)),fc=k=>col(fk.indexOf(k));
const pageHeader=19,pageEnd=pageHeader+data.pages.length;
style(main,`A1:N${pageEnd+2}`);main.tabColor='#243B53';
main.getRange(`A1:A${pageEnd+2}`).format.columnWidth=38;
main.getRange(`B1:B${pageEnd+2}`).format.columnWidth=20;
main.getRange(`C1:E${pageEnd+2}`).format.columnWidth=13;
main.getRange(`F1:I${pageEnd+2}`).format.columnWidth=17;
main.getRange(`J1:N${pageEnd+2}`).format.columnWidth=14;
main.getRange('A2').values=[['PaddleOCR-VL 输入处理对照']];
main.getRange('A2').format.font={name:'Arial',size:16,bold:true};
main.getRange('A3:N3').format.borders={bottom:{style:'thin',color:'#B7C4D2'}};
main.getRange('A4').values=[['同一模型、同一进程；4页失败样本＋3页成功控制。每方案每页测一次，预热单列。']];
main.getRange('A5').values=[['处理后方案含人工定框、去边缘、转正、先裁后缩及任务路由；不是官方自动版面流程。']];
main.getRange('A6').values=[['速度汇总按有效配对页累加，含失败成本；排除一页睡眠干扰，原始耗时保留。每区域上限4096 tokens。']];
main.getRange('A7').values=[['准确率是固定字段值匹配，参考未经人工双审。准备/合并另计，未含选框与历史PDF渲染成本。']];
main.getRange('A4:N7').format.font={name:'Arial',size:10,color:'#526577'};
main.getRange('A9:K9').values=[['范围','方案','计划页数','完整页数','限长页数','重复页数','有效配对识别\n合计秒（含失败）','正确字段','参考字段数','字段准确率','速度配对页数']];
header(main,'A9:K9');
main.getRange(`A${pageHeader}:N${pageHeader}`).values=[['父样本','方案','区域数','已落盘区域','完整输出','识别计算\n合计秒','含图片IO\n合计秒','裁剪准备秒','合并秒','正确字段','参考字段数','字段准确率','限长区域数','重复区域数']];
header(main,`A${pageHeader}:N${pageHeader}`);
const variants={baseline:'原方式',split:'处理后输入'};
const cohorts={all7:'全部7页',failure4:'原失败4页',control3:'成功控制3页'};
for(let i=0;i<data.pages.length;i++){
  const p=data.pages[i],row=pageHeader+1+i;
  main.getRange(`A${row}:N${row}`).values=[[p.parent_id,variants[p.variant],p.expected_regions,p.recorded_regions,p.completed==null?'待核对':p.completed?1:0,p.recognition_seconds_sum,p.request_wall_seconds_sum,p.preparation_seconds,p.merge_seconds,p.field_correct,p.field_total,p.field_accuracy,p.token_limit_regions,p.degenerate_regions]];
  const req=data.runs.map((r,j)=>({r,j})).filter(({r})=>r.parent_id===p.parent_id&&r.variant===p.variant&&r.phase==='measurement'&&r.recorded).map(({j})=>j+2);
  for(const [column,key]of [['F','recognition_or_failed_interval_seconds'],['G','request_wall_seconds']])if(req.length)main.getRange(`${column}${row}`).formulas=[[`=SUM(${req.map(j=>`'区域实测'!${rc(key)}${j}`).join(',')})`]];
  const checks=data.checks.map((c,j)=>({c,j})).filter(({c})=>c.parent_id===p.parent_id&&c.variant===p.variant&&c.reviewed).map(({j})=>j+2);
  if(checks.length){
    main.getRange(`J${row}`).formulas=[[`=SUM(${checks.map(j=>`'字段核对'!${fc('exact_match')}${j}`).join(',')})`]];
    if(p.field_accuracy!=null)main.getRange(`L${row}`).formulas=[[`=J${row}/K${row}`]];
  }
}
for(let i=0;i<data.summary.length;i++){
  const s=data.summary[i],row=i+10;
  main.getRange(`A${row}:K${row}`).values=[[cohorts[s.cohort]??s.cohort,variants[s.variant],s.pages_planned,s.completed,s.token_limit_pages,s.degenerate_pages,s.paired_valid_recognition_seconds_sum,s.field_correct,s.field_total,s.field_accuracy,s.paired_timing_valid_pages]];
  const pages=data.pages.map((p,j)=>({p,j})).filter(({p})=>p.variant===s.variant&&(s.cohort==='all7'||p.cohort===s.cohort)).map(({j})=>j+pageHeader+1);
  for(const [dest,source]of [['H','J'],['I','K']])main.getRange(`${dest}${row}`).formulas=[[`=SUM(${pages.map(j=>`${source}${j}`).join(',')})`]];
  const valid=data.pages.map((p,j)=>({p,j})).filter(({p})=>p.variant===s.variant&&(s.cohort==='all7'||p.cohort===s.cohort)&&p.paired_timing_valid).map(({j})=>j+pageHeader+1);
  if(valid.length)main.getRange(`G${row}`).formulas=[[`=SUM(${valid.map(j=>`F${j}`).join(',')})`]];
  if(s.field_accuracy!=null)main.getRange(`J${row}`).formulas=[[`=H${row}/I${row}`]];
}
main.getRange('G10:G15').setNumberFormat('0.000');main.getRange('J10:J15').setNumberFormat('0.0%');
main.getRange(`F20:I${pageEnd}`).setNumberFormat('0.000');main.getRange(`L20:L${pageEnd}`).setNumberFormat('0.0%');
main.getRange(`E20:E${pageEnd}`).conditionalFormats.add('cellIs',{operator:'equal',formula:0,format:{fill:'#FCE8E6'}});
main.getRange(`M20:N${pageEnd}`).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{fill:'#FFF1DA'}});
for(let i=0;i<data.pages.length;i++)if(!data.pages[i].paired_timing_valid){
  main.getRange(`F${i+20}:G${i+20}`).format.fill='#FFF1DA';
}
const supplement=JSON.parse(await fs.readFile(path.join(root,'output/paddle-ablation-20260929/refinement/data/benchmark.json'),'utf8'));
const recheck=JSON.parse(await fs.readFile(path.join(root,'output/paddle-ablation-20260929/timing-recheck/data/benchmark.json'),'utf8'));
const refinement=wb.worksheets.add('定向补测');
style(refinement,'A1:J25');refinement.getRange('A1:A25').format.columnWidth=44;
refinement.getRange('A2').values=[['双栏学历页面：四区域定向补测']];
refinement.getRange('A2').format.font={name:'Arial',size:16,bold:true};
refinement.getRange('A3').values=[['初轮失败后细分为本科、专科标题、左栏、右栏；全部重新推理。独立补测，不并入初轮准确率。']];
refinement.getRange('A4').values=[['同一模型与5个参考字段；每区域4096 tokens。准备耗时不含人工选框；预热不计入合计。']];
refinement.getRange('A6:J6').values=[['父样本','完整输出','区域数','识别合计秒','含图片IO秒','准备秒','正确字段','参考字段','字段准确率','限长区域']];header(refinement,'A6:J6');
const sr=supplement.summary[0];
refinement.getRange('A7:J7').values=[[sr.parent_id,sr.completed,sr.recorded_regions,sr.recognition_seconds_sum,sr.request_wall_seconds_sum,sr.preparation_seconds,sr.field_correct,sr.field_total,sr.field_accuracy,sr.token_limit_regions]];
refinement.getRange('D7:F7').setNumberFormat('0.000');refinement.getRange('I7').setNumberFormat('0.0%');
refinement.getRange('A10:F10').values=[['请求','阶段','识别秒','输出tokens','达到上限','复读']];header(refinement,'A10:F10');
supplement.regions.forEach((r,i)=>refinement.getRange(`A${11+i}:F${11+i}`).values=[[r.request_id,r.phase,r.recognition_or_failed_interval_seconds,r.output_tokens,r.token_limit,r.degenerate_repetition]]);
refinement.getRange('C11:C15').setNumberFormat('0.000');
const measuredRows=supplement.regions.map((r,i)=>({r,i})).filter(({r})=>r.phase==='measurement').map(({i})=>i+11);
refinement.getRange('D7').formulas=[[`=SUM(${measuredRows.map(i=>`C${i}`).join(',')})`]];
refinement.getRange('A18:D18').values=[['字段','参考值','识别值','正确']];header(refinement,'A18:D18');
const readable=v=>typeof v==='string'&&/^\d{12,}$/.test(v)?v.match(/.{1,4}/g).join(' '):v;
refinement.getRange('B19:C23').setNumberFormat('@');refinement.getRange('B19:C23').format.columnWidth=32;
supplement.checks.forEach((c,i)=>refinement.getRange(`A${i+19}:D${i+19}`).values=[[c.field,readable(c.reference_value),readable(c.predicted_value),c.exact_match]]);
if(sr.field_accuracy!=null){refinement.getRange('G7').formulas=[['=SUM(D19:D23)']];refinement.getRange('I7').formulas=[['=G7/H7']];}
const retest=wb.worksheets.add('计时复核');style(retest,'A1:I10');retest.getRange('A1:A10').format.columnWidth=24;
retest.getRange('A2').values=[['睡眠干扰后的独立配对复测']];retest.getRange('A2').format.font={name:'Arial',size:16,bold:true};
retest.getRange('A3').values=[['原请求2802.339秒覆盖Windows睡眠区间。原值保留；初轮速度配对排除该页，两种输入均重测。']];
retest.getRange('A4').values=[['此处为单次独立复核，未覆盖原始计时。预热单列在CSV，不计入表中。']];
retest.getRange('A6:I6').values=[['方案','完整输出','识别秒','含图片IO秒','输出tokens','正确字段','参考字段','字段准确率','复读']];header(retest,'A6:I6');
recheck.summary.forEach((r,i)=>{retest.getRange(`A${i+7}:I${i+7}`).values=[[variants[r.variant],r.completed,r.seconds,r.request_wall_seconds,r.tokens,r.field_correct,r.field_total,r.field_accuracy,r.degenerate_repetition]];retest.getRange(`H${i+7}`).formulas=[[`=F${i+7}/G${i+7}`]];});
retest.getRange('C7:D8').setNumberFormat('0.000');retest.getRange('H7:H8').setNumberFormat('0.0%');
wb.recalculate();
for(let i=0;i<data.summary.length;i++)for(const [c,k]of [['G','paired_valid_recognition_seconds_sum'],['H','field_correct'],['I','field_total'],['J','field_accuracy']]){
  const expected=data.summary[i][k],actual=main.getRange(`${c}${i+10}`).values[0][0];
  if(expected!=null&&Math.abs(expected-actual)>1e-7)throw new Error(`Summary mismatch ${c}${i+10}`);
  if(expected==null&&actual!=null&&actual!=='')throw new Error(`Missing result became numeric ${c}${i+10}`);
}
// Perturb one valid region to verify the region -> page -> summary dependency.
const probeIndex=data.runs.findIndex(r=>r.request_id==='baseline--medical-01-blood-p13');
const probe=detail.getRange(`${rc('recognition_or_failed_interval_seconds')}${probeIndex+2}`);
const before=probe.values[0][0],aggregateBefore=main.getRange('G10').values[0][0];
probe.values=[[before+1]];wb.recalculate();
if(Math.abs(main.getRange('G10').values[0][0]-aggregateBefore-1)>1e-7)throw new Error('Timing formula dependency failed');
probe.values=[[before]];wb.recalculate();
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!',options:{useRegex:true,maxResults:30}});
for(const [cell,key]of [['D7','recognition_seconds_sum'],['G7','field_correct'],['I7','field_accuracy']])if(sr[key]!=null&&Math.abs(refinement.getRange(cell).values[0][0]-sr[key])>1e-7)throw new Error(`Refinement mismatch ${cell}`);
console.log(errors.ndjson);
await fs.writeFile(path.join(out,'paddle-ablation-verification.json'),JSON.stringify({errors,summary:data.summary},null,2));
for(const [sheetName,range,name]of [['方案对照',`A1:N${pageEnd}`,'summary'],['区域实测','A1:J9','regions'],['字段核对','A1:I9','fields'],['定向补测','A1:J23','refinement'],['计时复核','A1:I9','recheck']]){
  const preview=await wb.render({sheetName,range,scale:1.2,format:'png'});
  await fs.writeFile(path.join(out,`paddle-ablation-${name}-preview.png`),new Uint8Array(await preview.arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'Paddle防截断对照.xlsx'));
console.log(JSON.stringify({output:path.join(out,'Paddle防截断对照.xlsx'),requests:data.runs.length,pages:data.pages.length,checks:data.checks.length}));
