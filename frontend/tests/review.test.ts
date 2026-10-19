import test from 'node:test'
import assert from 'node:assert/strict'
import { addedMember, buildReview, collectIssues, exportBlockReason, memberFields, spreadsheetName, summaryPatch } from '../src/review.ts'
import type { TaskResult } from '../src/business.ts'
const result = { task_id: 't', run_id: 'r', result_revision: 2, doc_type: 'DIPLOMA', status: 'NEED_REVIEW', review_issues: [], fields: [{ key: 'name', label: '姓名', value: null, review_issues: [] }, { key: 'certificate_no', label: '编号', value: '****1234', review_issues: [] }] } as unknown as TaskResult
test('review submits only changed values and never copied masked display values', () => {
  assert.deepEqual(buildReview(result, { fields: { name: '合成测试', certificate_no: '****1234' } }).fields, { name: '合成测试' })
  assert.throws(() => buildReview(result, { fields: { certificate_no: '****9999' } }), /MASKED/)
  assert.throws(() => buildReview(result, { fields: { age: Number.NaN } }), /INVALID_NUMBER/)
})
test('save acknowledgment is explicit and bound to the edited revision', () => {
  const body = buildReview(result, { fields: { name: '合成测试' }, confirm_export_disputes: true })
  assert.equal(body.confirm_export_disputes, true)
  assert.equal(body.expected_revision, result.result_revision)
  assert.equal(body.run_id, result.run_id)
  assert.deepEqual(body.fields, { name: '合成测试' })
  assert.equal(body.confirmed_disputes, undefined)
  assert.equal(buildReview(result, {}).confirm_export_disputes, undefined)
})
test('absence and explicit acceptance are distinct and version bound', () => {
  const r = { ...result, review_issues: [{ issue_id: 'i', code: 'CONFIDENCE_UNAVAILABLE', message: '未标定', can_accept: true }] }
  const body = buildReview(r, { absence_reasons: { name: 'NOT_ON_DOCUMENT' }, accepted_issues: [{ issue_id: 'i', reason: ' ' }] })
  assert.equal(body.expected_revision, 2)
  assert.equal(body.run_id, 'r')
  assert.equal(body.accepted_issues?.length, 1)
  assert.equal(body.accepted_issues?.[0]?.reason, undefined)
  assert.throws(() => buildReview(r, { accepted_issues: [{ issue_id: 'old', reason: '逐页核对' }] }))
  for (const code of ['MISSING','CONFLICT','INCOMPLETE_OUTPUT','MULTI_CANDIDATES','VALIDATION_FAILED','LOW_CONFIDENCE']) assert.throws(()=>buildReview({...r,review_issues:[{...r.review_issues[0]!,code}]},{accepted_issues:[{issue_id:'i'}]}))
})
test('issues include field, medical row and finding scopes without duplicates', () => {
  const issue = { issue_id: 'i', code: 'MISSING', message: '待补', can_accept: false }
  const r = { ...result, items: [{ name: '项目', review_issues: [issue] }], report_summary: { findings: [{ review_issues: [{ ...issue, issue_id: 'f' }] }] } } as unknown as TaskResult
  assert.equal(collectIssues(r).length, 2)
})
test('issue rows carry editor jump anchors for fields, items, findings and members', () => {
  const issue = (id: string) => ({ issue_id: id, code: 'MISSING', message: '待补', can_accept: false })
  const r = { ...result, review_issues: [issue('task')], fields: [{ key: 'name', label: '姓名', value: null, review_issues: [issue('f1')] }], items: [{ item_id: 'it1', name: '项目', review_issues: [issue('i1')] }], report_summary: { findings: [{ finding_id: 'fd1', review_issues: [issue('d1')] }] }, members: [{ member_id: 'm1', source_page: 1, name: { key: 'name', label: '姓名', value: '张三', review_issues: [issue('m1')] } }] } as unknown as TaskResult
  assert.deepEqual(collectIssues(r).map(row => row.jump), [
    undefined,
    { kind: 'field', id: 'name' },
    { kind: 'item', id: 'it1' },
    { kind: 'finding', id: 'fd1' },
    { kind: 'member', id: '0' },
  ])
})
test('export uses saved required-field eligibility independently of review status', () => {
  assert.ok(exportBlockReason([]))
  assert.match(exportBlockReason([{ status: 'COMPLETED', export_ready: false }])!, /必填未填、识别有异议/)
  assert.equal(exportBlockReason([{ status: 'NEED_REVIEW', export_ready: true }, { status: 'FAILED', export_ready: true }]), null)
  assert.ok(exportBlockReason([{ status: 'NEED_REVIEW', export_ready: true }, { status: 'NEED_REVIEW', export_ready: false }]))
  // Old servers remain authoritative when they omit the new optional flag.
  assert.equal(exportBlockReason([{ status: 'NEED_REVIEW' }]), null)
})
test('medical review and automatic acceptance omit excluded measurements and subsection summaries', () => {
  const issue = (id: string) => ({ issue_id: id, code: 'CONFIDENCE_UNAVAILABLE', message: '未标定', can_accept: true })
  const r = { ...result, doc_type: 'MEDICAL_REPORT', fields: [], items: [
    { name: '身高', abnormal_exclusion_reason: 'HEIGHT_WEIGHT', review_issues: [issue('height')] },
    { name: '体重', abnormal_exclusion_reason: 'HEIGHT_WEIGHT', review_issues: [issue('weight')] },
    { name: '小结', abnormal_exclusion_reason: 'SECTION_SUMMARY', review_issues: [issue('summary')] },
    { name: '体重指数', review_issues: [issue('bmi')] },
  ] } as unknown as TaskResult
  assert.deepEqual(collectIssues(r).map(row => row.issue.issue_id), ['bmi'])
  assert.deepEqual(buildReview(r, { accepted_issues: [{ issue_id: 'bmi' }] }).accepted_issues, [{ issue_id: 'bmi' }])
  for (const id of ['height', 'weight', 'summary']) assert.throws(() => buildReview(r, { accepted_issues: [{ issue_id: id }] }), /INVALID_ACCEPTANCE/)
})

test('added members require actual source page and name, and reject masks',()=>{
  assert.deepEqual(addedMember({name:'合成成员',occupation:''},2,3),{fields:{name:'合成成员'},source_page:2})
  assert.throws(()=>addedMember({name:''},1,1))
  assert.throws(()=>addedMember({name:'合成成员'},2,1))
  assert.throws(()=>addedMember({name:'****'},1,1))
  assert.equal(memberFields({member_id:'opaque',source_page:1,name:{key:'name',label:'姓名'}}).length,1)
})

test('report count belongs only to declared follow-up scope and requires title evidence',()=>{
  assert.throws(()=>summaryPatch(undefined,'follow_up_required',2,'','人工核对',1,1),/TITLE/)
  assert.deepEqual(summaryPatch(undefined,'follow_up_required',2,'您共有2项异常需进一步检查并治疗：','人工核对',1,1),{scope:'follow_up_required',reason:'人工核对',source_page:1,declared_count:2,title:'您共有2项异常需进一步检查并治疗：'})
  assert.equal(summaryPatch(undefined,'overall_conclusion',8,'','人工核对',1,1).declared_count,undefined)
  assert.throws(()=>summaryPatch(undefined,'unidentified',undefined,'','人工核对',2,1),/SOURCE/)
})
test('spreadsheetName uses material types and Shanghai export time across midnight', () => {
  const at = new Date('2026-10-08T16:05:09Z')
  assert.equal(spreadsheetName(['MEDICAL_REPORT'], at), '体检报告_20261009_000509.xlsx')
  assert.equal(spreadsheetName(['DIPLOMA', 'DIPLOMA', 'DEGREE_CERT'], at), '毕业证+学位证_20261009_000509.xlsx')
  assert.equal(spreadsheetName(['BANK_CARD'], new Date('2026-10-08T15:59:59Z')), '银行卡_20261008_235959.xlsx')
})

test('added member validation uses current shared requirements with legacy defaults',()=>{
  assert.deepEqual(addedMember({gender:'F'},1,1,['gender']),{fields:{gender:'F'},source_page:1})
  assert.throws(()=>addedMember({name:'合成成员'},1,1,['gender']),/MEMBER_SOURCE/)
  assert.deepEqual(addedMember({},1,1,[]),{fields:{},source_page:1})
  assert.throws(()=>addedMember({gender:'****'},1,1,[]),/MASKED/)
  assert.throws(()=>addedMember({},0,1,[]),/MEMBER_SOURCE/)
})
test('spreadsheetName only uses known material labels and a safe fallback', () => {
  const at = new Date('2026-10-09T07:15:30Z')
  assert.equal(spreadsheetName([], at), '识别结果_20261009_151530.xlsx')
  assert.equal(spreadsheetName([undefined, '../../private', 'toString'], at), '识别结果_20261009_151530.xlsx')
  const types = ['ID_CARD_FRONT', 'ID_CARD_BACK', 'PASSPORT', 'HOUSEHOLD_REGISTER', 'BUSINESS_LICENSE', 'GENERIC', 'XUEXIN_DIPLOMA_TABLE']
  assert.equal(spreadsheetName(types, at), '身份证人像面+身份证国徽面+护照+户口本+营业执照+通用识别+学历证书电子注册备案表_20261009_151530.xlsx')
})
