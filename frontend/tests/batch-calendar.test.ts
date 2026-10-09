import test from 'node:test'
import assert from 'node:assert/strict'
import { groupBatchEntries, periodBounds } from '../src/batchCalendar.ts'
import type { BatchEntry } from '../src/monitor.ts'

test('calendar bounds use Monday weeks and real month lengths across years', () => {
  assert.deepEqual(periodBounds('2026-01-01', 'week'), { date_from: '2025-12-29', date_to: '2026-01-04' })
  assert.deepEqual(periodBounds('2024-02-20', 'month'), { date_from: '2024-02-01', date_to: '2024-02-29' })
  assert.deepEqual(periodBounds('2026-12-31', 'day'), { date_from: '2026-12-31', date_to: '2026-12-31' })
  for (const input of [null, '', '2026-02-30', '2026-2-1', 'invalid']) assert.equal(periodBounds(input, 'day'), null)
})

test('batch groups use Shanghai midnight and descending order without mutating input', () => {
  const item = (id: string, created_at: string) => ({ id, entry: { batch: { batch_id: id, status: 'COMPLETED', created_at }, tasks: [], tasksLoaded: true, expanded: false } as BatchEntry })
  const values = [item('old', '2026-10-08T15:59:59Z'), item('new', '2026-10-08T16:00:00Z'), item('latest', '2026-10-09T01:00:00Z')]
  const groups = groupBatchEntries(values, 'day')
  assert.deepEqual(groups.map(g => g.label), ['2026-10-09', '2026-10-08'])
  assert.deepEqual(groups[0]!.entries.map(e => e.id), ['latest', 'new'])
  assert.deepEqual(values.map(e => e.id), ['old', 'new', 'latest'])
  assert.equal(groupBatchEntries(values, 'week').length, 1)
  assert.equal(groupBatchEntries(values, 'month')[0]!.label, '2026年10月')
  const pending = { id: 'pending', entry: { batch: null, tasks: [], tasksLoaded: false, expanded: true } }
  assert.equal(groupBatchEntries([pending, ...values], 'day')[0]!.label, '新批次 · 正在同步')
})
