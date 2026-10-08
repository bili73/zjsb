import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const data = JSON.parse(await fs.readFile(path.join(root, 'output/benchmark-data/benchmark.json'), 'utf8'));
const out = path.join(root, 'outputs/01a0e741-2881-71e0-9d30-b7b4caecde0a');
await fs.mkdir(out, { recursive: true });
const wb = Workbook.create();
const summary = wb.worksheets.add('模型汇总');
const detail = wb.worksheets.add('逐次实测');
const fields = wb.worksheets.add('参考核对');
const cards = wb.worksheets.add('银行卡核对');
const runEnd = data.runs.length + 1;
const navy = '#243B53';
const blue = '#EAF0F6';

function col(index) {
  let text = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) text = String.fromCharCode(65 + (n - 1) % 26) + text;
  return text;
}
function style(sheet, endRow, endCol) {
  sheet.showGridLines = false;
  const range = sheet.getRange(`A1:${col(endCol - 1)}${endRow}`);
  range.format.font = { name: 'Arial', size: 10, color: '#172B4D' };
  range.format.columnWidth = 17;
  range.format.rowHeight = 23;
  range.format.verticalAlignment = 'center';
}
function header(sheet, row, count) {
  const range = sheet.getRange(`A${row}:${col(count - 1)}${row}`);
  range.format.fill = navy;
  range.format.font = { bold: true, color: '#FFFFFF', name: 'Arial', size: 10 };
  range.format.wrapText = true;
  range.format.horizontalAlignment = 'center';
  range.format.rowHeight = 38;
}
function dataSheet(sheet, rows, tableName) {
  const keys = Object.keys(rows[0]);
  style(sheet, rows.length + 1, keys.length);
  sheet.getRange(`A1:${col(keys.length - 1)}${rows.length + 1}`).setNumberFormat('@');
  // Group long identifiers for legible previews; canonical unspaced strings stay in CSV/JSON.
  const displayValue = (key, value) => ['reference_text', 'reference_card_number', 'predicted_card_number'].includes(key)
    && typeof value === 'string' && /^\d{12,}$/.test(value) ? value.match(/.{1,4}/g).join(' ') : value ?? null;
  sheet.getRange(`A1:${col(keys.length - 1)}${rows.length + 1}`).values = [keys, ...rows.map(r => keys.map(k => displayValue(k, r[k])))];
  sheet.tables.add(`A1:${col(keys.length - 1)}${rows.length + 1}`, true, tableName);
  header(sheet, 1, keys.length);
  sheet.getRange(`A1:${col(keys.length - 1)}1`).format.rowHeight = 52;
  keys.forEach((key, index) => {
    const range = sheet.getRange(`${col(index)}2:${col(index)}${rows.length + 1}`);
    if (rows.some(r => typeof r[key] === 'number')) range.setNumberFormat(key.includes('_s') || key.endsWith('_gib') ? '0.000' : '0');
    else range.setNumberFormat('@');
  });
  sheet.freezePanes.freezeRows(1);
  return keys;
}

const runKeys = dataSheet(detail, data.runs, 'OcrRuns');
const fieldKeys = dataSheet(fields, data.field_checks, 'ReferenceMatches');
const cardKeys = dataSheet(cards, data.bankcard_checks, 'BankCardMatches');
detail.getRange(`A1:C${runEnd}`).format.columnWidth = 22;
detail.getRange(`D1:D${runEnd}`).format.columnWidth = 24;
detail.getRange(`F2:F${runEnd}`).conditionalFormats.add('cellIs', { operator: 'equal', formula: 0, format: { fill: '#FCE8E6', font: { color: '#B42318' } } });
detail.getRange('K2').formulas = [['=J2/I2']];
detail.getRange(`K2:K${runEnd}`).fillDown();
// Preserve long identifiers and paths as text; table columns remain flat for export.
for (const key of ['model_revision', 'source_sha256', 'input_sha256', 'source', 'metric_file', 'output_file']) {
  const column = col(runKeys.indexOf(key));
  detail.getRange(`${column}1:${column}${runEnd}`).format.columnWidth = 48;
}
for (const key of ['field_accuracy', 'character_error_rate', 'word_error_rate']) {
  const column = col(runKeys.indexOf(key));
  detail.getRange(`${column}2:${column}${runEnd}`).setNumberFormat('0.0%');
}
fields.getRange('A1:C115').format.columnWidth = 22;
fields.getRange('D1:D115').format.columnWidth = 19;
fields.getRange('E1:E115').format.columnWidth = 30;
fields.getRange('E2:E115').setNumberFormat('@');
fields.getRange('H1:J115').format.columnWidth = 46;
fields.getRange('F2:F115').conditionalFormats.add('cellIs', { operator: 'equal', formula: 0, format: { fill: '#FFF1DA', font: { color: '#8A4B00' } } });
cards.getRange('A1:D13').format.columnWidth = 22;
cards.getRange('E1:F13').format.columnWidth = 30;
cards.getRange('J2:J13').setNumberFormat('0.0%');
cards.getRange('K1:N13').format.columnWidth = 48;
cards.getRange('G2:G13').conditionalFormats.add('cellIs', { operator: 'equal', formula: 0, format: { fill: '#FCE8E6', font: { color: '#B42318' } } });

style(summary, 34, 14);
summary.tabColor = navy;
summary.getRange('A2').values = [['OCR 模型实测数据']];
summary.getRange('A2').format.font = { size: 16, bold: true };
summary.getRange('A3:N3').format.borders = { bottom: { style: 'thin', color: '#B7C4D2' } };
summary.getRange('A4').values = [['共同 10 份用于同样本比较。耗时含截断，排除加载、图片读取和结果写入。']];
summary.getRange('A5').values = [['覆盖率仅为初步参考字符串命中比例。正式准确率、CER、WER 尚无数据。']];
summary.getRange('A4:N5').format.font = { size: 10, color: '#526577' };
summary.getRange('A7:N7').values = [['批次', '样本范围', '模型', '尝试数', '完整输出', '截断数', '完成率', '平均耗时\n秒/页', '中位耗时\n秒/页', '分配显存\n峰值 GiB', '参考命中数', '参考总数', '初步字符串\n覆盖率', '初步卡号\n整号匹配率']];
header(summary, 7, 14);
summary.getRange('A1:C28').format.columnWidth = 22;
summary.getRange('D1:G28').format.columnWidth = 12;
summary.getRange('H1:N28').format.columnWidth = 15;
summary.getRange('A29').values = [['速度限制：未统一预热和重复测量，证书续跑期间存在其他 GPU 任务干扰。']];
summary.getRange('A30').values = [['配置：RTX 3060 12GB；GLM/Paddle 为 BF16；Chandra 为 NF4，使用回退实现。']];
summary.getRange('A31').values = [['Paddle 为元素识别接口处理整页。体检样本仅一份报告的两页。']];
summary.getRange('A32').values = [[`${data.runs.length} 条推理明细。另存 3 条兼容性失败和 1 次启动失败。卡号匹配率仅核对完整号码。`]];
summary.getRange('A33').values = [['参考值未经人工双审。银行卡裁剪只测试 1 张失败样本，不代表 3 张全部改善后的准确率。']];
summary.getRange('A34').values = [['长编号以分组文本显示，CSV/JSON 保留连续数字。统计口径见 output/benchmark-data/README.md。']];
summary.getRange('A29:N34').format.font = { size: 10, color: '#526577' };
const summaries = [...data.summary].sort((a,b) => Number(b.cohort === 'common10') - Number(a.cohort === 'common10'));
const cohortLabels = { common10: '共同 10 份', all_available: '各模型全部扩样', education_document: '毕业证 1 份', medical_report: '体检报告 2 页' };
const expectedSummary = [];
for (let i = 0; i < summaries.length; i++) {
  const s = summaries[i];
  const row = i + 8;
  const indexes = data.runs.map((r,j) => ({r,j})).filter(({r}) => r.batch === s.batch && r.model === s.model && (s.cohort === 'all_available' || (s.cohort === 'common10' && r.common10) || r.document_type === s.cohort)).map(({j}) => j+2);
  const refs = column => indexes.map(j => `'逐次实测'!${column}${j}`).join(',');
  const batchLabel = { 'certificate-batch': '证书扩样', 'smoke-test': '初测', 'bankcard-baseline': '银行卡原图', 'bankcard-crop': '银行卡手动裁剪' }[s.batch];
  const cohortLabel = s.batch === 'bankcard-baseline' ? '共同 3 张原图' : s.batch === 'bankcard-crop' ? '恒丰卡 1 张' : cohortLabels[s.cohort];
  summary.getRange(`A${row}:C${row}`).values = [[batchLabel, cohortLabel, s.model]];
  summary.getRange(`D${row}:J${row}`).formulas = [[`=COUNT(${refs('I')})`, `=SUM(${refs('F')})`, `=SUM(${refs('H')})`, `=E${row}/D${row}`, `=AVERAGE(${refs('I')})`, `=MEDIAN(${refs('I')})`, `=MAX(${refs('L')})`]];
  if (s.cohort === 'common10') {
    summary.getRange(`K${row}:M${row}`).formulas = [[`=SUMIFS('参考核对'!$F$2:$F$115,'参考核对'!$B$2:$B$115,C${row})`, `=COUNTIFS('参考核对'!$B$2:$B$115,C${row})`, `=K${row}/L${row}`]];
    summary.getRange(`A${row}:N${row}`).format.fill = blue;
  }
  if (s.batch.startsWith('bankcard-')) {
    summary.getRange(`N${row}`).formulas = [[`=SUMIFS('银行卡核对'!$G$2:$G$13,'银行卡核对'!$A$2:$A$13,"${s.batch}",'银行卡核对'!$B$2:$B$13,C${row})/D${row}`]];
  }
  expectedSummary.push([s.attempted, s.completed, s.truncated, s.completion_rate, s.elapsed_mean_s, s.elapsed_median_s, s.max_allocated_gib, s.reference_found_count, s.reference_check_count, s.provisional_text_coverage]);
}
summary.getRange('D8:F25').setNumberFormat('0');
summary.getRange('G8:G25').setNumberFormat('0.0%');
summary.getRange('H8:J25').setNumberFormat('0.00');
summary.getRange('K8:L25').setNumberFormat('0');
summary.getRange('M8:N25').setNumberFormat('0.0%');
summary.getRange('F8:F25').conditionalFormats.add('cellIs', { operator: 'greaterThan', formula: 0, format: { fill: '#FCE8E6', font: { color: '#B42318' } } });

// Restore a temporary perturbation to verify that the detail-to-summary formulas are live.
const before = detail.getRange('I2').values[0][0];
detail.getRange('I2').values = [[before + 10]];
const changedMean = summary.getRange('H8').values[0][0];
if (Math.abs(changedMean - (expectedSummary[0][4] + 1)) > 1e-8) throw new Error('Summary did not recalculate after detail edit');
detail.getRange('I2').values = [[before]];
wb.recalculate();
const actual = summary.getRange('D8:M25').values;
for (let i = 0; i < data.bankcard_checks.length; i++) {
  for (const [column, key] of [['E', 'reference_card_number'], ['F', 'predicted_card_number']]) {
    const saved = cards.getRange(`${column}${i+2}`).values[0][0];
    if (typeof saved !== 'string' || saved.replace(/\s/g, '') !== data.bankcard_checks[i][key]) throw new Error('Card identifier changed');
  }
}
for (let i = 0; i < expectedSummary.length; i++) {
  for (let j = 0; j < 10; j++) {
    const expected = expectedSummary[i][j];
    if (expected !== null && Math.abs(actual[i][j] - expected) > 1e-8) throw new Error(`Mismatch row ${i+8} column ${j+4}`);
    if (expected === null && actual[i][j] !== null && actual[i][j] !== '') throw new Error('Missing metric became a value');
  }
}
for (let i = 0; i < summaries.length; i++) {
  const expected = summaries[i].provisional_card_exact_match_rate;
  if (expected !== null && Math.abs(summary.getRange(`N${i+8}`).values[0][0] - expected) > 1e-8) throw new Error('Card rate mismatch');
}
const inspected = await wb.inspect({ kind: 'region', sheetId: summary.name, range: 'A7:N10', maxChars: 4000, tableMaxCols: 14 });
await fs.writeFile(path.join(out, 'verification.json'), JSON.stringify({ summary: actual, inspection: inspected }, null, 2));
const errors = await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 30 }, summary: 'formula error scan' });
console.log(errors.ndjson);
for (const [sheetName, range, filename] of [['模型汇总', 'A1:N34', 'summary'], ['逐次实测', 'A1:M12', 'runs'], ['参考核对', 'A1:G13', 'fields'], ['银行卡核对', 'A1:J13', 'cards']]) {
  const png = await wb.render({ sheetName, range, scale: 1.3, format: 'png' });
  await fs.writeFile(path.join(out, `${filename}-preview.png`), new Uint8Array(await png.arrayBuffer()));
}
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(path.join(out, 'OCR实测数据.xlsx'));
console.log(JSON.stringify({ rows: data.runs.length, fields: data.field_checks.length, output: path.join(out, 'OCR实测数据.xlsx'), verified: true }));
