import test from 'node:test'
import assert from 'node:assert/strict'
import { hasMissingRequiredFields, requiredFieldLabels, hasExportDisputes, disputedFieldLabels, parseResult } from '../src/business.ts'
import type { DocProfile, Task } from '../src/business.ts'

const catalogue: DocProfile[] = [{ doc_type: 'DIPLOMA', label: '毕业证', fields: [
  { key: 'school_name', label: '学校名称', required: true, editable: true, type: 'string' },
  { key: 'graduate_date', label: '毕业日期', required: true, editable: true, type: 'date' },
  { key: 'gender', label: '性别', required: false, editable: true, type: 'enum' },
] }]
const missing = { status: 'NEED_REVIEW' as const, doc_type: 'DIPLOMA', export_ready: false,
  export_blockers: [{ field: 'school_name', code: 'MISSING' }, { field: 'graduate_date', code: 'MISSING' }] }

test('tables show actual export requirements, including partial output and invalid grids', () => {
  const table={...missing,doc_type:'TABLE',export_blockers:[{field:'tables[0].title',code:'MISSING'},
    {field:'tables[0].header_rows',code:'MISSING'},{field:'tables[0]',code:'INCOMPLETE_OUTPUT'},
    {field:'tables[0]',code:'INVALID_TABLE'}]}
  assert.deepEqual(requiredFieldLabels(table,[]),['表格标题缺失或不确定','表头行数不确定','识别不完整，需补正或确认','表格结构需修正'])
  assert.deepEqual(requiredFieldLabels({...table,export_blockers:[{field:'tables',code:'MISSING'}]},[]),['未获得可导出的表格'])
  assert.equal(hasMissingRequiredFields({...table,export_ready:true,export_blockers:[]}),false)
})

test('missing markers use saved required blockers, not review state or optional metadata', () => {
  assert.equal(hasMissingRequiredFields(missing), true)
  assert.deepEqual(requiredFieldLabels(missing, catalogue), ['学校名称', '毕业日期'])
  assert.equal(hasMissingRequiredFields({ ...missing, status: 'COMPLETED' }), true)
  assert.equal(hasMissingRequiredFields({ ...missing, export_ready: true, export_blockers: [] }), false)
  assert.deepEqual(requiredFieldLabels({ ...missing, export_ready: true }, catalogue), [])
})

test('pending work, unavailable results and absent legacy flags do not invent missing fields', () => {
  for (const status of ['QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'] as Task['status'][]) {
    assert.equal(hasMissingRequiredFields({ ...missing, status }), false)
  }
  assert.equal(hasMissingRequiredFields({ ...missing, status: 'FAILED', export_blockers: [{ field: 'task', code: 'MISSING' }] }), false)
  assert.equal(hasMissingRequiredFields({ ...missing, export_blockers: [{ field: 'doc_type', code: 'MISSING' }] }), false)
  assert.equal(hasMissingRequiredFields({ ...missing, export_ready: undefined }), false)
  assert.deepEqual(requiredFieldLabels({ ...missing, export_ready: undefined }, catalogue), [])
})

test('member and generic missing fields are readable and unknown keys stay visible', () => {
  const task = { ...missing, export_blockers: [
    { field: 'members[0].name', code: 'MISSING' },
    { field: 'members[1].name', code: 'MISSING' },
    { field: 'generic.full_text', code: 'MISSING' },
    { field: 'future_key', code: 'MISSING' },
  ] }
  assert.deepEqual(requiredFieldLabels(task, catalogue), ['成员 1 / 姓名', '成员 2 / 姓名', '正文', 'future_key'])
})

test('blocker details stay authoritative when catalogue is absent, conditional or repeated', () => {
  assert.deepEqual(requiredFieldLabels(missing, []), ['school_name', 'graduate_date'])
  const task = { ...missing, export_blockers: [
    { field: 'graduate_date', code: 'MISSING' },
    { field: 'graduate_date', code: 'MISSING' },
    { field: 'gender', code: 'FORMAT' },
  ] }
  assert.deepEqual(requiredFieldLabels(task, catalogue), ['毕业日期'])
  assert.equal(hasMissingRequiredFields({ ...missing, export_blockers: undefined }), false)
  assert.deepEqual(requiredFieldLabels({ ...missing, export_blockers: undefined }, catalogue), [])
})

test('disputes have independent batch markers, names and do not masquerade as missing fields', () => {
  const task = { ...missing, export_blockers: [{ field: 'graduate_date', code: 'DISPUTED' }] }
  assert.equal(hasMissingRequiredFields(task), false)
  assert.equal(hasExportDisputes(task), true)
  assert.deepEqual(disputedFieldLabels(task, catalogue), ['毕业日期'])
  assert.deepEqual(requiredFieldLabels(task, catalogue), [])
  const both = { ...task, export_blockers: [...task.export_blockers, ...missing.export_blockers] }
  assert.equal(hasMissingRequiredFields(both), true)
  assert.equal(hasExportDisputes(both), true)
  assert.deepEqual(disputedFieldLabels({ ...task, export_blockers: [
    {field:'task',code:'DISPUTED'}, {field:'items[3]',code:'DISPUTED'},
    {field:'members[1].id_number',code:'DISPUTED'}]}, []), ['材料一致性','检测项目','成员 2 / 公民身份号码'])
})

test('result contract validates opaque dispute IDs and confirmation eligibility', () => {
  const id = '00000000-0000-4000-8000-000000000001'
  const dispute = { dispute_id: 'd_' + 'a'.repeat(64), field:'certificate_no',label:'编号',code:'NUMBER_LENGTH',message:'19位',can_confirm:true }
  const result = { task_id:id,run_id:id,result_revision:1,doc_type:'DIPLOMA',status:'NEED_REVIEW',review_issues:[],fields:[],export_disputes:[dispute] }
  assert.equal(parseResult(result).export_disputes?.[0]?.can_confirm, true)
  for (const bad of [{...dispute,dispute_id:'bad'}, {...dispute,can_confirm:'true'}, {...dispute,message:null}])
    assert.throws(() => parseResult({...result,export_disputes:[bad]}), /INVALID_RESPONSE/)
})

test('saving clears a marker while unresolved review state and unfiltered tasks are retained', () => {
  const tasks = [missing, { ...missing, export_ready: true, export_blockers: [] }]
  assert.equal(tasks.filter(hasMissingRequiredFields).length, 1)
  const saved = tasks.map(task => ({ ...task, export_ready: true, export_blockers: [] }))
  assert.equal(saved.filter(hasMissingRequiredFields).length, 0)
  assert.equal(saved.length, 2)
  assert.ok(saved.every(task => task.status === 'NEED_REVIEW'))
  assert.equal(tasks.length, 2)
})
