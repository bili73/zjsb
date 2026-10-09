import test from 'node:test'
import assert from 'node:assert/strict'
import { sourceSelection } from '../src/sourceLocation.ts'

test('every same-page selection has fresh identity and an independent box', () => {
  const original = { page: 1, bbox: [.1, .2, .8, .3] as [number, number, number, number] }
  const first = sourceSelection(original), again = sourceSelection(original)
  assert.notEqual(first, again)
  assert.notEqual(first.bbox, original.bbox)
  assert.deepEqual(first, again)
  assert.equal(sourceSelection({}).page, 1)
})
