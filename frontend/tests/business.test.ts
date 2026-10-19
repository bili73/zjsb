import test from 'node:test'
import assert from 'node:assert/strict'
import {
  docTypes, fieldValueText, genderText, idNumberLengthWarning, isRecord, medicalFlag, parseBatches, parseCreated, parseResult, parseTask, parseTasks, parseUser,
  validateUpload, hasResult, resultKey, matchesMedicalFilter,
} from '../src/business.ts'

const id = '11111111-2222-4333-8444-555555555555'
const other = '99999999-8888-4777-8666-555555555555'

const user = { user_id: 'u1', display_name: '操作员', role: 'operator', permissions: ['tasks:write'] }

test('ID length hints count X and whitespace without changing saved values or drafts', () => {
  const extra = '110105194912310002X'
  assert.equal(extra.length, 19)
  assert.equal(idNumberLengthWarning(extra), '身份证号当前为19位，比18位多1位。请对照原件人工核对，系统不会自动改号。')
  assert.equal(idNumberLengthWarning('11010519491231002'), '身份证号当前为17位，比18位少1位。请对照原件人工核对，系统不会自动改号。')
  assert.match(idNumberLengthWarning('110105491231002'), /15位，比18位少3位/)
  for (const value of [null, undefined, '', '  ', '11010519491231002X', '11010519491231002x', '110105194912310021', ' 110105 19491231 002X\n']) {
    assert.equal(idNumberLengthWarning(value), '')
  }
  const field = { key: 'id_number', value: extra, source: { raw_text: '1 1 0 1 0 5 1 9 4 9 1 2 3 1 0 0 0 2 X' } }
  const before = structuredClone(field)
  assert.match(idNumberLengthWarning(field.value), /多1位/)
  assert.deepEqual(field, before)
})

test('batch owner descriptor accepts explicit historical nulls and rejects malformed attribution', () => {
  const batch = { batch_id: id, status: 'PROCESSING', owner: { user_id: id, username: 'alice', display_name: '张三', account_exists: true } }
  const parse = (value: unknown) => parseBatches({ items: [value], total: 1, page: 1, page_size: 50 })
  assert.equal(parse(batch).items[0]?.owner?.display_name, '张三')
  assert.equal(parse({ ...batch, owner: { user_id: null, username: null, display_name: null, account_exists: false } }).total, 1)
  assert.equal(parse({ batch_id: id, status: 'PROCESSING' }).total, 1)
  for (const owner of [null, {}, { ...batch.owner, account_exists: 'true' }, { ...batch.owner, user_id: 5 },
    { ...batch.owner, username: 'invalid name' }, { ...batch.owner, display_name: 5 },
    { ...batch.owner, user_id: null }, { ...batch.owner, username: null }]) {
    assert.throws(() => parse({ ...batch, owner }), /INVALID_RESPONSE/)
  }
})

test('medical field text distinguishes recognized normal, absent and unrecognized results', () => {
  const field = { key: 'liver_function', label: '肝功五项', value: null, confidence: null, confidence_method: 'unavailable' as const, need_review: false, review_issues: [] }
  assert.equal(fieldValueText({ ...field, value: '未见异常' }, true), '未见异常')
  assert.equal(fieldValueText({ ...field, value: 'ALT 80 U/L' }, true), 'ALT 80 U/L')
  assert.equal(fieldValueText(field, true), '未识别')
  assert.equal(fieldValueText({ ...field, absence_reason: 'NOT_ON_DOCUMENT' }, true), '报告未载明')
  assert.equal(fieldValueText({ ...field, absence_reason: 'NOT_ON_DOCUMENT' }), '未载明')
  assert.equal(fieldValueText({ ...field, absence_reason: 'NOT_APPLICABLE' }, true), '不适用')
  assert.equal(fieldValueText({ ...field, value: '人工值', absence_reason: 'NOT_ON_DOCUMENT' }, true), '人工值')
  assert.equal(fieldValueText({ ...field, key: 'gender', value: 'F' }), '女')
})

test('optional saved export eligibility validates flags and safe blocker paths for tasks and results', () => {
  const task = { task_id: id, run_id: id, result_revision: 1, cancel_requested: false, status: 'FAILED', page_count: 1, pages: [] }
  const result = { task_id: id, run_id: id, result_revision: 1, status: 'NEED_REVIEW', doc_type: 'DIPLOMA', fields: [], review_issues: [] }
  for (const [parser, base] of [[parseTask, task], [parseResult, result]] as const) {
    assert.equal(parser(base).export_ready, undefined)
    assert.equal(parser({ ...base, export_ready: true, export_blockers: [] }).export_ready, true)
    const blockers = [{ field: 'members[0].name', code: 'MISSING' }, { field: 'generic.full_text', code: 'MISSING' }]
    assert.deepEqual(parser({ ...base, export_ready: false, export_blockers: blockers }).export_blockers, blockers)
    for (const flag of [null, 'true', 1]) assert.throws(() => parser({ ...base, export_ready: flag }), /INVALID_RESPONSE/)
    for (const blockers of [null, {}, [{ field: '<raw>', code: 'MISSING' }], [{ field: 'name', code: 1 }], [{ field: 'name' }]]) {
      assert.throws(() => parser({ ...base, export_blockers: blockers }), /INVALID_RESPONSE/)
    }
  }
})

test('parseUser accepts a valid operator and rejects malformed roles', () => {
  assert.deepEqual(parseUser(user).role, 'operator')
  assert.throws(() => parseUser({ ...user, role: 'root' }), /INVALID_RESPONSE/)
  assert.throws(() => parseUser(null), /INVALID_RESPONSE/)
})

test('progress_detail accepts measured region counts with nullable totals and rejects invented numbers', () => {
  const task = { task_id: id, run_id: id, result_revision: 1, cancel_requested: false, status: 'OCR', page_count: 2, pages: [] }
  const detail = { stage: 'OCR', prepared_pages: 2, total_pages: 2, processed_regions: 3, recognized_regions: 2, incomplete_regions: 1, total_regions: 4 }
  assert.deepEqual(parseTask({ ...task, progress_detail: detail }).progress_detail, detail)
  const unknown = { ...detail, total_pages: null, total_regions: null }
  assert.deepEqual(parseTask({ ...task, progress_detail: unknown }).progress_detail, unknown)
  assert.equal(parseTask({ ...task, actual_source_page_count: null }).actual_source_page_count, null)
  assert.equal(parseTask(task).progress_detail, undefined)
  for (const bad of [
    { total_regions: -1 },
    { processed_regions: 1.5 },
    { total_regions: '4' },
    { recognized_regions: null },
    { stage: 5 },
    { ...detail, stage: 'EXTRACTING' },
    { ...detail, stage: 'GENERATING' },
    { ...detail, processed_regions: 4 },
    { ...detail, total_regions: 2 },
    { ...detail, total_regions: 0 },
    { ...detail, total_pages: 1 },
    { ...detail, total_pages: 0 },
    { total_pages: null, total_regions: null },
    [],
  ]) assert.throws(() => parseTask({ ...task, progress_detail: bad }), /INVALID_RESPONSE/)
})

test('isRecord filters arrays and null', () => {
  assert.equal(isRecord({}), true)
  assert.equal(isRecord([]), false)
  assert.equal(isRecord(null), false)
})

test('parseTask validates optional batch_id and sanitizes error payloads', () => {
  const task = { task_id: id, batch_id: other, run_id: id, result_revision: 1, cancel_requested: false, status: 'OCR', page_count: 2, pages: [] }
  assert.equal(parseTask(task).batch_id, other)
  assert.throws(() => parseTask({ ...task, batch_id: 'not-a-uuid' }), /INVALID_RESPONSE/)
  assert.throws(() => parseTask({ ...task, progress: 101 }), /INVALID_RESPONSE/)
  const withError = parseTask({ ...task, error: { code: 'WEIRD_CODE', error_id: 'e_abc', stage: 'OCR' } })
  assert.equal(withError.error?.code, 'UNKNOWN_ERROR')
  assert.equal(withError.error?.error_id, 'e_abc')
  assert.throws(() => parseTasks([{ ...task, status: 'RUNNING' }]), /INVALID_RESPONSE/)
})

test('task scheduling timestamps remain optional for old servers and validate new responses', () => {
  const task = { task_id: id, run_id: id, result_revision: 1, cancel_requested: false, status: 'QUEUED', page_count: 0, pages: [] }
  assert.equal(parseTask(task).queued_at, undefined)
  assert.equal(parseTask(task).active_started_at, undefined)
  const queued = { ...task, queued_at: '2026-10-16T02:00:00Z', active_started_at: null }
  assert.equal(parseTask(queued).queued_at, queued.queued_at)
  assert.equal(parseTask(queued).active_started_at, null)
  const active = { ...queued, status: 'OCR', active_started_at: '2026-10-16T02:01:00Z' }
  assert.equal(parseTask(active).active_started_at, active.active_started_at)
  for (const invalid of ['', 'broken', 123, {}, []]) {
    assert.throws(() => parseTask({ ...queued, queued_at: invalid }), /INVALID_RESPONSE/)
    assert.throws(() => parseTask({ ...queued, active_started_at: invalid }), /INVALID_RESPONSE/)
  }
  assert.equal(parseTask({ ...queued, queued_at: null }).queued_at, null)
})

test('parseBatches rejects unknown batch status', () => {
  const list = { items: [{ batch_id: id, status: 'PROCESSING' }], total: 1, page: 1, page_size: 50 }
  assert.equal(parseBatches(list).total, 1)
  assert.throws(() => parseBatches({ ...list, items: [{ batch_id: id, status: 'WEIRD' }] }), /INVALID_RESPONSE/)
})

test('parseCreated validates uuid shape', () => {
  assert.deepEqual(parseCreated({ batch_id: id, task_ids: [other] }), { batch_id: id, task_ids: [other] })
  assert.throws(() => parseCreated({ batch_id: id, task_ids: ['x'] }), /INVALID_RESPONSE/)
})

const makeField = (overrides: Record<string, unknown> = {}) => ({
  key: 'school', label: '学校', value: '某大学', value_masked: null, confidence: 0.92, confidence_method: 'calibrated',
  need_review: false, review_issues: [], ...overrides,
})

const makeItem = (overrides: Record<string, unknown> = {}) => ({
  item_id: 'i1', name: '白细胞计数', alias: 'WBC', category: '血常规', result_raw: '3.2', unit: '10^9/L',
  reference_range: '3.5-9.5', value_num: 3.2, ref_low: 3.5, ref_high: 9.5,
  abnormal_flag: 'LOW', reported_abnormal_marker: null, abnormal_basis: 'reference_comparison',
  confidence: 0.88, confidence_method: 'calibrated', need_review: false, review_issues: [], ...overrides,
})

const makeMedicalResult = (overrides: Record<string, unknown> = {}) => ({
  task_id: id, run_id: id, result_revision: 1, doc_type: 'MEDICAL_REPORT', status: 'COMPLETED', review_issues: [],
  basic_info: { name: makeField({ key: 'name', label: '姓名' }) },
  items: [makeItem()],
  abnormal_summary: [makeItem()],
  normal_summary: '其余项目在参考范围内',
  stats: { total: 1, normal: 0, abnormal: 1, unknown: 0, categories: ['血常规'] },
  ...overrides,
})

test('height and weight exclusion preserves facts and removes both filtered views while BMI remains', () => {
  const excluded = parseResult(makeMedicalResult({ items: [makeItem({ name: '身高', abnormal_exclusion_reason: 'HEIGHT_WEIGHT' })] })).items![0]!
  assert.equal(excluded.abnormal_flag, 'LOW')
  assert.equal(matchesMedicalFilter(excluded, 'all'), true)
  assert.equal(matchesMedicalFilter(excluded, 'abnormal'), false)
  assert.equal(matchesMedicalFilter({ ...excluded, abnormal_flag: 'UNKNOWN' }, 'unknown'), false)
  assert.equal(medicalFlag(excluded), '不计异常')
  const bmi = { ...excluded, name: '体重指数', abnormal_exclusion_reason: null }
  assert.equal(matchesMedicalFilter(bmi, 'abnormal'), true)
  assert.equal(medicalFlag(bmi), '偏低')
  const summary = parseResult(makeMedicalResult({ items: [makeItem({ name: '小结', abnormal_exclusion_reason: 'SECTION_SUMMARY' })] })).items![0]!
  assert.equal(matchesMedicalFilter(summary, 'abnormal'), false)
  assert.equal(medicalFlag(summary), '小结 · 不计项目')
  for (const reason of [true, 'BMI', {}, ['HEIGHT_WEIGHT']]) assert.throws(() => parseResult(makeMedicalResult({ items: [makeItem({ abnormal_exclusion_reason: reason })] })), /INVALID_RESPONSE/)
})

test('parseResult accepts report_grade abnormal basis (regression: retired UI rejected it)', () => {
  const graded = makeItem({ item_id: 'i2', name: '谷丙转氨酶', abnormal_flag: 'ABNORMAL', abnormal_basis: 'report_grade', risk_grade: '↑', diagnosis: '偏高' })
  const result = parseResult(makeMedicalResult({ items: [makeItem(), graded], abnormal_summary: [graded] }))
  assert.equal(result.items[1]?.abnormal_basis, 'report_grade')
  assert.equal(result.items[1]?.risk_grade, '↑')
})

test('parseResult rejects contradictory report summaries', () => {
  const followUp = { scope: 'follow_up_required', declared_count: 1, count_check: 'match', sources: [], findings: [{ finding_id: id, reported_number: '1', text: '复查', sources: [] }] }
  assert.equal(parseResult(makeMedicalResult({ report_summary: followUp })).report_summary?.scope, 'follow_up_required')
  assert.throws(() => parseResult(makeMedicalResult({ report_summary: { ...followUp, declared_count: 2 } })), /INVALID_RESPONSE/)
  assert.throws(() => parseResult(makeMedicalResult({ report_summary: { ...followUp, scope: 'overall_conclusion' } })), /INVALID_RESPONSE/)
  assert.equal(parseResult(makeMedicalResult({ report_summary: { scope: 'unidentified', declared_count: null, count_check: 'unverified', sources: [], findings: [] } })).report_summary?.scope, 'unidentified')
})

test('parseResult enforces medical payload shape and source geometry', () => {
  assert.throws(() => parseResult(makeMedicalResult({ stats: undefined })), /INVALID_RESPONSE/)
  assert.throws(() => parseResult(makeMedicalResult({ items: [makeItem({ confidence: 1.5 })] })), /INVALID_RESPONSE/)
  const badBox = makeField({ source: { page: 1, bbox: [0.5, 0.1, 0.2, 0.9] } })
  assert.throws(() => parseResult(makeMedicalResult({ basic_info: { name: badBox } })), /INVALID_RESPONSE/)
  const masked = makeField({ value: null, value_masked: '1101**********0011' })
  assert.equal(parseResult(makeMedicalResult({ basic_info: { name: masked } })).basic_info?.name?.value_masked, '1101**********0011')
})

test('parseResult keeps certificate results minimal', () => {
  const cert = { task_id: id, run_id: id, result_revision: 2, doc_type: 'DIPLOMA', status: 'COMPLETED', review_issues: [], fields: [makeField()] }
  const parsed = parseResult(cert)
  assert.equal(parsed.fields?.[0]?.label, '学校')
  assert.equal(parsed.items, undefined)
})

test('hasResult and resultKey behave', () => {
  assert.equal(hasResult({ status: 'NEED_REVIEW' }), true)
  assert.equal(hasResult({ status: 'OCR' }), false)
  assert.equal(resultKey({ task_id: id, run_id: other, result_revision: 3 }), `${id}:${other}:3`)
})

const file = (name: string, size: number) => ({ name, size })

test('validateUpload covers count, type, size and batch limits', () => {
  assert.match(validateUpload([])!, /1–100/)
  assert.match(validateUpload([file('a.exe', 10)])!, /JPG/)
  assert.match(validateUpload([file('a.png', 0)])!, /内容为空/)
  assert.match(validateUpload([file('a.png', 50 * 1024 * 1024 + 1)])!, /50 MB/)
  assert.match(validateUpload(Array.from({ length: 101 }, () => file('a.png', 100)))!, /1–100/)
  const fullBatch = Array.from({ length: 10 }, () => file('a.pdf', 50 * 1024 * 1024))
  assert.equal(validateUpload(fullBatch), null)
  assert.match(validateUpload([...fullBatch, file('extra.png', 1)])!, /500 MB/)
  assert.equal(validateUpload(Array.from({ length: 100 }, () => file('a.png', 100))), null)
  assert.equal(validateUpload([file('体检报告.PDF', 1024), file('x.jpeg', 2048), file('y.heic', 512)]), null)
})

test('docTypes includes the independent photo-table entry and canonical identifiers', () => {
  assert.equal(Object.keys(docTypes).length, 14)
  assert.equal(docTypes.TABLE, '表格')
  assert.equal(docTypes.MEDICAL_REPORT, '体检报告')
  assert.equal(docTypes.BANK_CARD, '银行卡')
  assert.equal(docTypes.GENERIC, '通用识别')
  assert.equal(Object.hasOwn(docTypes, 'GENERAL'), false)
  assert.equal(Object.hasOwn(docTypes, 'ID_CARD'), false)
  assert.ok(docTypes.ID_CARD_FRONT && docTypes.ID_CARD_BACK && docTypes.XUEXIN_DIPLOMA_TABLE)
})

test('medicalFlag formatting', () => {
  assert.equal(medicalFlag(makeItem()), '偏低')
  assert.equal(medicalFlag(makeItem({ abnormal_basis: 'unknown', abnormal_flag: 'UNKNOWN' })), '待判定')
  assert.equal(medicalFlag(makeItem({ abnormal_flag: 'ABNORMAL', abnormal_basis: 'report_grade' })), '异常')
})

test('genderText maps contract M/F values to 男/女 and passes others through', () => {
  assert.equal(genderText('M'), '男')
  assert.equal(genderText('F'), '女')
  assert.equal(genderText('男'), '男')
  assert.equal(genderText(null), '')
  assert.equal(genderText(undefined), '')
  assert.equal(genderText('X'), 'X')
  assert.equal(genderText(3), '3')
})


test('medical project field preserves ordered names and validates multiple sources', () => {
  const source = { page: 19, bbox: [0.1,0.2,0.8,0.3], bbox_kind: 'cell', raw_text: '眼科常规' }
  const field = { key: 'exam_projects', label: '体检项目', value: '眼科常规；内科检查', confidence: null, confidence_method: 'unavailable', need_review: false, review_issues: [], source, sources: [source] }
  const base = { task_id: id, run_id: id, result_revision: 1, doc_type: 'MEDICAL_REPORT', status: 'NEED_REVIEW', review_issues: [], fields: [field], basic_info: { exam_projects: field }, items: [], abnormal_summary: [], stats: { total: null, normal: null, abnormal: null, unknown: null, categories: [] } }
  assert.equal(parseResult(base).fields?.[0]?.value, '眼科常规；内科检查')
  assert.equal(parseResult(base).fields?.[0]?.sources?.[0]?.page, 19)
  for (const sources of [null, {}, [{ ...source, page: 0 }], [{ ...source, bbox: [0.8,0.2,0.1,0.3] }]]) {
    assert.throws(() => parseResult({ ...base, fields: [{ ...field, sources }] }), /INVALID_RESPONSE/)
  }
})
