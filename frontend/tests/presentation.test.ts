import test from 'node:test'
import assert from 'node:assert/strict'
import { batchOwnerLabel, expiryText, fairQueueHint, formatTime, shanghaiDate, sortBatchTasks, taskProgressView } from '../src/presentation.ts'
import type { ProgressDetail, Task, TaskStatus } from '../src/business.ts'

function namedTask(task_id: string, file_name?: string): Task {
  return { task_id, file_name, run_id: 'run', result_revision: 1, cancel_requested: false,
    status: 'QUEUED', page_count: 1, pages: [] }
}

test('batch files use natural numeric filename order without changing inputs or task references', () => {
  const input = Object.freeze(['10.jpg', '2.jpg', '1.jpg', '材料10.pdf', '材料2.pdf'].map(name => Object.freeze(namedTask(name, name))))
  const ordered = sortBatchTasks(input)
  assert.deepEqual(ordered.map(task => task.file_name), ['1.jpg', '2.jpg', '10.jpg', '材料2.pdf', '材料10.pdf'])
  assert.deepEqual(input.map(task => task.file_name), ['10.jpg', '2.jpg', '1.jpg', '材料10.pdf', '材料2.pdf'])
  for (const task of input) assert.strictEqual(ordered.find(item => item.task_id === task.task_id), task)
})

test('filename ties and missing names stay deterministic when the response order changes', () => {
  const tasks = [namedTask('z', 'same.jpg'), namedTask('b', ' '), namedTask('a'),
    namedTask('a2', 'same.jpg'), namedTask('lower', 'a.jpg'), namedTask('upper', 'A.jpg')]
  const ids = (input: readonly Task[]) => sortBatchTasks(input).map(task => task.task_id)
  assert.deepEqual(ids(tasks), ['upper', 'lower', 'a2', 'z', 'a', 'b'])
  assert.deepEqual(ids([...tasks].reverse()), ids(tasks))
  assert.deepEqual(sortBatchTasks([]), [])
})

test('recognition completion, review saves and reruns do not move batch files', () => {
  const tasks = [namedTask('ten', '10.jpg'), namedTask('two', '2.jpg'), namedTask('one', '1.jpg')]
  const refreshed = [...tasks].reverse().map((task, index) => ({ ...task,
    run_id: `new-run-${index}`, result_revision: index + 2,
    status: (index === 0 ? 'COMPLETED' : index === 1 ? 'NEED_REVIEW' : 'QUEUED') as TaskStatus }))
  assert.deepEqual(sortBatchTasks(refreshed).map(task => task.task_id), ['one', 'two', 'ten'])
})

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

test('expiry displays only server deadlines and never without a seven-day fallback', () => {
  assert.equal(expiryText('2026-10-03T18:00:00Z'), '最近材料 2026-10-04 02:00:00 到期清理')
  assert.equal(expiryText(null), '永不自动清除')
  for (const value of [undefined, '', 'broken']) assert.equal(expiryText(value), '')
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

test('queued tasks explain account turns and show only observed timestamps in Shanghai time', () => {
  const queued = taskProgressView({ ...progressTask('QUEUED'), queued_at: '2026-10-16T02:00:00Z', active_started_at: null })
  assert.equal(queued.label, '排队等待')
  assert.match(queued.tooltip, /本次入队：2026-10-16 10:00:00（UTC\+8）/)
  assert.ok(queued.tooltip.includes(fairQueueHint))
  assert.doesNotMatch(queued.tooltip, /实际开始|已准备|已识别|预计|第\s*\d+\s*位/)
  const legacy = taskProgressView({ status: 'QUEUED' })
  assert.equal(legacy.tooltip, fairQueueHint)
  const active = taskProgressView({ ...progressTask('OCR'), queued_at: '2026-10-16T02:00:00Z', active_started_at: '2026-10-16T02:01:00Z' })
  assert.match(active.tooltip, /实际开始：2026-10-16 10:01:00（UTC\+8）/)
  assert.match(active.tooltip, /已识别/)
  assert.ok(!active.tooltip.includes(fairQueueHint))
})

test('stopped tasks retain this run timestamps without inventing missing historical starts', () => {
  const stopped = taskProgressView({ status: 'COMPLETED', queued_at: '2026-10-16T02:00:00Z', active_started_at: '2026-10-16T02:01:00Z' })
  assert.match(stopped.tooltip, /本次入队/)
  assert.match(stopped.tooltip, /实际开始/)
  assert.equal(stopped.active, false)
  const legacy = taskProgressView({ status: 'COMPLETED', queued_at: null, active_started_at: null })
  assert.equal(legacy.tooltip, '')
  const legacyQueued = taskProgressView({ status: 'QUEUED', queued_at: null, active_started_at: null })
  assert.equal(legacyQueued.tooltip, fairQueueHint)
})
