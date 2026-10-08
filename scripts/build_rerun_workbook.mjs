import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const data = JSON.parse(await fs.readFile(path.join(root, 'output/benchmark-rerun-data/benchmark.json'), 'utf8'));
const out = path.join(root, 'outputs/01a0e741-2881-71e0-9d30-b7b4caecde0a');
await fs.mkdir(out, { recursive: true });
const wb = Workbook.create();
const summary = wb.worksheets.add('重测汇总');
const detail = wb.worksheets.add('逐次实测');
const checks = wb.worksheets.add('字段核对');
const col = i => { let s=''; for(let n=i+1;n;n=Math.floor((n-1)/26)) s=String.fromCharCode(65+(n-1)%26)+s; return s; };
function base(sheet, range) {
  sheet.showGridLines = false;
  const r=sheet.getRange(range);
  r.format.font={name:'Arial',size:10,color:'#172B4D'};
  r.format.rowHeight=24;
  r.format.columnWidth=17;
  r.format.verticalAlignment='center';
}
function header(sheet, range) {
  const r=sheet.getRange(range);
  r.format.fill='#243B53';
  r.format.font={name:'Arial',size:10,color:'#FFFFFF',bold:true};
  r.format.horizontalAlignment='center';
  r.format.wrapText=true;
  r.format.rowHeight=48;
}
function rawSheet(sheet, rows, name) {
  const keys=Object.keys(rows[0]);
  const end=rows.length+1;
  const range=`A1:${col(keys.length-1)}${end}`;
  base(sheet,range);
  sheet.getRange(range).setNumberFormat('@');
  const display=(v) => typeof v==='string' && /^\d{12,}$/.test(v) ? v.match(/.{1,4}/g).join(' ') : v??null;
  sheet.getRange(range).values=[keys,...rows.map(r=>keys.map(k=>display(r[k])))];
  sheet.tables.add(range,true,name);
  header(sheet,`A1:${col(keys.length-1)}1`);
  keys.forEach((key,i)=>{
    const r=sheet.getRange(`${col(i)}2:${col(i)}${end}`);
    if(rows.some(x=>typeof x[key]==='number')) r.setNumberFormat(/accuracy|rate/.test(key)?'0.0%': /_s$|gib/.test(key)?'0.000':'0');
    if(/file|value|reference_status|source|session/.test(key)) sheet.getRange(`${col(i)}1:${col(i)}${end}`).format.columnWidth=38;
  });
  sheet.getRange(`A1:D${end}`).format.columnWidth=24;
  sheet.freezePanes.freezeRows(1);
  return keys;
}
const runKeys=rawSheet(detail,data.runs,'RerunMeasurements');
const checkKeys=rawSheet(checks,data.checks,'ReviewedFields');
const refCol=col(checkKeys.indexOf('reference_value'));
const predCol=col(checkKeys.indexOf('predicted_value'));
checks.getRange(`${refCol}2:${predCol}${data.checks.length+1}`).format.wrapText=true;
data.checks.forEach((r,i)=>{
  const length=Math.max(String(r.reference_value??'').length,String(r.predicted_value??'').length);
  if(length>28) checks.getRange(`${refCol}${i+2}:${predCol}${i+2}`).format.rowHeight=Math.ceil(length/25)*17;
});
const correctCol=col(checkKeys.indexOf('exact_match'));
checks.getRange(`${correctCol}2:${correctCol}${data.checks.length+1}`).conditionalFormats.add('cellIs',{operator:'equal',formula:0,format:{fill:'#FFF1DA'}});

const end=data.summary.length+8;
base(summary,`A1:O${end}`);
summary.tabColor='#243B53';
summary.getRange('A2').values=[['OCR 重测：速度与字段准确率']];
summary.getRange('A2').format.font={name:'Arial',size:16,bold:true};
summary.getRange('A3:O3').format.borders={bottom:{style:'thin',color:'#B7C4D2'}};
summary.getRange('A4').values=[['速度只比较三模型共同完整输出的相同输入；预热、截断、重启中断不计入正常耗时。']];
summary.getRange('A5').values=[['准确率为已标注字段的匹配率，截断仍逐项评分；参考由助手看图初审，未经人工双审。']];
summary.getRange('A6').values=[['各样本仅测一次；Chandra 为 NF4，其余 BF16。新增体检来自同品牌模板，不能代表跨医院效果。']];
summary.getRange('A4:O6').format.font={name:'Arial',size:10,color:'#526577'};
if(data.audit.missing_measurements.length) {
  summary.getRange('A7').values=[[`尚缺 ${data.audit.missing_measurements.length} 条测量；相应准确率留空。新增体检的三模型共同速度待补齐后计算。`]];
  summary.getRange('A7').format.font={name:'Arial',size:10,color:'#8A4B00'};
}
summary.getRange('A8:O8').values=[['批次','样本组','模型','计划数','完整输出','截断数','共同完成数','共同平均\n秒/页','共同中位\n秒/页','正确字段','已核对字段','初步字段\n准确率','缺测数','未核对字段','运行会话']];
header(summary,'A8:O8');
summary.getRange(`A1:C${end}`).format.columnWidth=23;
summary.getRange(`D1:G${end}`).format.columnWidth=12;
summary.getRange(`H1:N${end}`).format.columnWidth=15;
summary.getRange(`O1:O${end}`).format.columnWidth=38;
const labels={certificate:'证书 10 份',medical_report:'原体检 2 页',bankcard_original:'银行卡原图 3 张',bankcard_crop:'银行卡裁剪 1 张',blood:'新增血常规',conclusion:'新增结论页',followup_urine_ultrasound:'新增长截图',all_selected:'新增体检全部'};
const batchLabels={rerun:'原样本重测',medical_expansion:'新增体检'};
const rc=k=>col(runKeys.indexOf(k));
const cc=k=>col(checkKeys.indexOf(k));
for(let i=0;i<data.summary.length;i++) {
  const s=data.summary[i], row=i+9;
  summary.getRange(`A${row}:O${row}`).values=[[batchLabels[s.batch]??s.batch,labels[s.group]??s.group,s.model,s.planned,s.completed,s.truncated,s.comparable_n,s.comparable_mean_s,s.comparable_median_s,s.field_correct,s.field_total,s.field_accuracy,s.missing_metrics,s.unreviewed_fields,s.sessions]];
  const match=r=>r.batch===s.batch && (r.group===s.group || s.group==='all_selected');
  const paired=data.runs.map((r,j)=>({r,j})).filter(({r})=>match(r)&&r.model===s.model&&r.selected_measurement&&r.common_complete).map(({j})=>j+2);
  if(paired.length!==s.comparable_n) throw new Error(`Comparable denominator mismatch ${s.group} ${s.model}`);
  if(paired.length) {
    const refs=paired.map(j=>`'逐次实测'!${rc('elapsed_s')}${j}`).join(',');
    summary.getRange(`H${row}:I${row}`).formulas=[[`=AVERAGE(${refs})`,`=MEDIAN(${refs})`]];
  }
  const reviewed=data.checks.map((r,j)=>({r,j})).filter(({r})=>match(r)&&r.model===s.model&&r.reviewed).map(({j})=>j+2);
  if(reviewed.length!==s.field_total) throw new Error(`Field denominator mismatch ${s.group} ${s.model}`);
  if(reviewed.length) {
    summary.getRange(`J${row}`).formulas=[[`=SUM(${reviewed.map(j=>`'字段核对'!${cc('exact_match')}${j}`).join(',')})`]];
    summary.getRange(`L${row}`).formulas=[[`=J${row}/K${row}`]];
  }
}
summary.getRange(`D9:G${end}`).setNumberFormat('0');
summary.getRange(`H9:I${end}`).setNumberFormat('0.00');
summary.getRange(`J9:K${end}`).setNumberFormat('0');
summary.getRange(`L9:L${end}`).setNumberFormat('0.0%');
summary.getRange(`M9:N${end}`).setNumberFormat('0');
summary.getRange(`F9:F${end}`).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{fill:'#FCE8E6'}});
summary.getRange(`M9:N${end}`).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{fill:'#FFF1DA'}});
const bloodTitle=end+3, bloodHeader=end+5;
base(summary,`A${bloodTitle}:G${bloodHeader+3}`);
summary.getRange(`A1:C${bloodHeader+3}`).format.columnWidth=23;
summary.getRange(`D1:G${bloodHeader+3}`).format.columnWidth=12;
summary.getRange(`A${bloodTitle}`).values=[['新增血常规结果单独核对']];
summary.getRange(`A${bloodTitle}`).format.font={name:'Arial',size:14,bold:true};
summary.getRange(`A${bloodTitle+1}`).values=[['固定参考含 72 个结果，其中 6 个带异常箭头；数值和箭头须同时匹配。']];
summary.getRange(`A${bloodHeader}:G${bloodHeader}`).values=[['模型','结果正确数','已核对结果数','结果准确率','含箭头正确数','已核对箭头项','含箭头准确率']];
header(summary,`A${bloodHeader}:G${bloodHeader}`);
data.summary.filter(s=>s.batch==='medical_expansion'&&s.group==='all_selected').forEach((s,i)=>{
  const row=bloodHeader+1+i;
  summary.getRange(`A${row}:G${row}`).values=[[s.model,s.blood_results_correct,s.blood_results_reviewed,s.blood_results_accuracy,s.blood_abnormal_results_correct,s.blood_abnormal_results_reviewed,s.blood_abnormal_results_accuracy]];
  for(const [column,rateColumn,denomColumn,abnormal] of [['B','D','C',false],['E','G','F',true]]) {
    const ix=data.checks.map((c,j)=>({c,j})).filter(({c})=>c.batch==='medical_expansion'&&c.model===s.model&&c.reviewed&&c.field.startsWith('血常规_')&&(!abnormal||/[↑↓]/.test(c.reference_value))).map(({j})=>j+2);
    if(ix.length) {
      summary.getRange(`${column}${row}`).formulas=[[`=SUM(${ix.map(j=>`'字段核对'!${cc('exact_match')}${j}`).join(',')})`]];
      summary.getRange(`${rateColumn}${row}`).formulas=[[`=${column}${row}/${denomColumn}${row}`]];
    }
  }
});
summary.getRange(`D${bloodHeader+1}:D${bloodHeader+3}`).setNumberFormat('0.0%');
summary.getRange(`G${bloodHeader+1}:G${bloodHeader+3}`).setNumberFormat('0.0%');
// Verify a real dependency, then restore the measured value before export.
const probe=data.runs.findIndex(r=>r.selected_measurement&&r.common_complete);
if(probe>=0) {
  const run=data.runs[probe];
  const i=data.summary.findIndex(s=>s.batch===run.batch&&s.group===run.group&&s.model===run.model);
  const cell=detail.getRange(`${rc('elapsed_s')}${probe+2}`);
  const original=cell.values[0][0];
  cell.values=[[original+1]];
  const changed=summary.getRange(`H${i+9}`).values[0][0];
  if(Math.abs(changed-data.summary[i].comparable_mean_s-1/data.summary[i].comparable_n)>1e-8) throw new Error('Summary dependency did not recalculate');
  cell.values=[[original]];
}
wb.recalculate();
for(let i=0;i<data.summary.length;i++) {
  for(const [column,key] of [['H','comparable_mean_s'],['I','comparable_median_s'],['J','field_correct'],['L','field_accuracy']]) {
    const actual=summary.getRange(`${column}${i+9}`).values[0][0], expected=data.summary[i][key];
    if(expected!=null && Math.abs(actual-expected)>1e-8) throw new Error(`Formula mismatch ${column}${i+9}`);
    if(expected==null && actual!=null && actual!=='') throw new Error('Missing value became numeric');
  }
}
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:30}});
console.log(errors.ndjson);
await fs.writeFile(path.join(out,'rerun-verification.json'),JSON.stringify({runs:data.runs.length,checks:data.checks.length,summary:data.summary,errors},null,2));
for(const [sheetName,range,name] of [['重测汇总',`A1:N${bloodHeader+3}`,'summary'],['逐次实测','A1:J9','runs'],['字段核对','A1:J10','checks']]) {
  const png=await wb.render({sheetName,range,scale:1.2,format:'png'});
  await fs.writeFile(path.join(out,`rerun-${name}-preview.png`),new Uint8Array(await png.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'OCR重测_速度与准确率.xlsx'));
console.log(JSON.stringify({output:path.join(out,'OCR重测_速度与准确率.xlsx'),runs:data.runs.length,checks:data.checks.length}));
