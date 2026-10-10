import test from 'node:test'
import assert from 'node:assert/strict'
import { hasMissingRequiredFields, requiredFieldLabels } from '../src/business.ts'
import type { DocProfile, Task } from '../src/business.ts'

const catalogue: DocProfile[] = [{ doc_type: 'DIPLOMA', label: '毕业证', fields: [
  { key: 'school_name', label: '学校名称', required: true, editable: true, type: 'string' },
  { key: 'graduate_date', label: '毕业日期', required: true, editable: true, type: 'date' },
  { key: 'gender', label: '性别', required: false, editable: true, type: 'enum' },
] }]
const missing = { status: 'NEED_REVIEW' as const, doc_type: 'DIPLOMA', export_ready: false,
  export_blockers: [{ field: 'school_name', code: 'MISSING' }, { field: 'graduate_date', code: 'MISSING' }] }

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
  assert.equal(hasMissingRequiredFields({ ...missing, export_blockers: undefined }), true)
  assert.deepEqual(requiredFieldLabels({ ...missing, export_blockers: undefined }, catalogue), [])
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
