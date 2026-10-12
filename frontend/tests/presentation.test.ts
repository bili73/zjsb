import test from 'node:test'
import assert from 'node:assert/strict'
import { batchOwnerLabel, expiryText, formatTime, shanghaiDate, taskProgressView } from '../src/presentation.ts'
import type { ProgressDetail, TaskStatus } from '../src/business.ts'

test('batch attribution distinguishes named, deleted, historical and unknown uploaders', () => {
  const owner = { user_id: 'immutable-id', username: 'alice', display_name: '张三', account_exists: true }
  assert.equal(batchOwnerLabel(owner), '张三（alice）')
  assert.equal(batchOwnerLabel({ ...owner, account_exists: false }), '张三（alice，已删除）')
  assert.equal(batchOwnerLabel({ ...owner, username: null, display_name: null, account_exists: false }), '历史账号（未关联）')
  assert.equal(batchOwnerLabel({ ...owner, user_id: null, username: null, display_name: null, account_exists: false }), '未知上传人')
  assert.equal(batchOwnerLabel(undefined), '未知上传人')
})

test('display timestamps use Shanghai across UTC midnight and explicit offsets', () => {
  assert.equal(formatTime('2026-10-08T17:02:03Z'), '2026-10-09 01:02:03')
  assert.equal(formatTime('2026-10-09T01:02:03+08:00'), '2026-10-09 01:02:03')
  assert.equal(shanghaiDate(new Date('2026-12-31T17:00:00Z')), '20270101')
  for (const value of [undefined, null, '', 'broken']) assert.equal(formatTime(value), '—')
})

test('expiry date is creation plus the 7-day retention, dated in Shanghai', () => {
  assert.equal(expiryText('2026-10-03T18:00:00Z'), '2026-10-11')
  assert.equal(expiryText('2026-10-03T10:00:00+08:00'), '2026-10-10')
  assert.equal(expiryText('2026-02-25T20:00:00+08:00'), '2026-03-04')
  for (const value of [undefined, null, '', 'broken']) assert.equal(expiryText(value), '')
})

function progressTask(status: TaskStatus, detail: Partial<ProgressDetail> = {}) {
  return { status, progress_detail: { stage: status, prepared_pages: 2, total_pages: 2,
    processed_regions: 0, recognized_regions: 0, incomplete_regions: 0, total_regions: 4, ...detail } }
}

test('only known OCR work gets a measured bar; preparation/mapping/validation stay visibly active', () => {
  const queued = taskProgressView(progressTask('QUEUED'))
  assert.equal(queued.active, false)
  assert.equal(queued.percentage, null)
  assert.equal(queued.amount, '')
  const preparing = taskProgressView(progressTask('PREPROCESSING', { prepared_pages: 2, total_pages: 8 }))
  assert.equal(preparing.amount, '已准备 2/8 页')
  assert.equal(preparing.percentage, null)
  assert.equal(preparing.active, true)
  const ocr = taskProgressView(progressTask('OCR', { processed_regions: 3, recognized_regions: 3 }))
  assert.equal(ocr.percentage, 75)
  assert.equal(ocr.amount, '已处理 3/4 个区域')
  for (const status of ['EXTRACTING', 'VALIDATING'] as const) {
    const view = taskProgressView(progressTask(status, { processed_regions: 4, recognized_regions: 4 }))
    assert.equal(view.active, true)
    assert.equal(view.percentage, null)
    assert.equal(view.amount, '已处理 4/4 个区域')
    assert.match(view.label, /中$/)
  }
})

test('unknown/zero plans and legacy percentages never become invented numeric progress', () => {
  const unknown = taskProgressView(progressTask('OCR', { total_regions: null, processed_regions: 1, recognized_regions: 1 }))
  assert.equal(unknown.percentage, null)
  assert.equal(unknown.amount, '已处理 1 个区域（总数未知）')
  const native = taskProgressView(progressTask('EXTRACTING', { total_regions: 0 }))
  assert.equal(native.amount, '无需图像识别')
  assert.equal(native.active, true)
  assert.equal(native.percentage, null)
  const old = { status: 'OCR' as const, progress: 90 }
  assert.equal(taskProgressView(old).percentage, null)
  assert.equal(taskProgressView(old).amount, '')
})

test('stopped work retains counts and incomplete warnings without a success bar or spinner', () => {
  for (const status of ['NEED_REVIEW', 'COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED'] as const) {
    const view = taskProgressView(progressTask(status, { processed_regions: 3, recognized_regions: 2, incomplete_regions: 1 }))
    assert.equal(view.percentage, null)
    assert.equal(view.active, false)
    assert.equal(view.amount, '已处理 3/4 个区域')
    assert.equal(view.incomplete, 1)
    assert.match(view.tooltip, /不代表准确率、剩余时间或人工核对通过/)
    if (status === 'NEED_REVIEW') assert.match(view.label, /待核对/)
  }
})

test('rounding does not show complete OCR units before the final region finishes', () => {
  const task = progressTask('OCR', { processed_regions: 199, recognized_regions: 199, total_regions: 200 })
  assert.equal(taskProgressView(task).percentage, 99)
  task.progress_detail.processed_regions = task.progress_detail.recognized_regions = 200
  assert.equal(taskProgressView(task).percentage, 100)
  assert.equal(taskProgressView(task).active, true)
})
