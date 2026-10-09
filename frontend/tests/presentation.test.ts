import test from 'node:test'
import assert from 'node:assert/strict'
import { formatTime, shanghaiDate } from '../src/presentation.ts'

test('display timestamps use Shanghai across UTC midnight and explicit offsets', () => {
  assert.equal(formatTime('2026-10-08T17:02:03Z'), '2026-10-09 01:02:03')
  assert.equal(formatTime('2026-10-09T01:02:03+08:00'), '2026-10-09 01:02:03')
  assert.equal(shanghaiDate(new Date('2026-12-31T17:00:00Z')), '20270101')
  for (const value of [undefined, null, '', 'broken']) assert.equal(formatTime(value), '—')
})
