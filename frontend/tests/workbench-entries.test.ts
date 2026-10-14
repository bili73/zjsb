import test from 'node:test'
import assert from 'node:assert/strict'
import { WORKBENCH_MAX_ENTRIES, loadWorkbenchLayout, saveWorkbenchLayout, splitEntries } from '../src/workbenchEntries.ts'

const keys = ['A', 'B', 'C', 'D']
function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
  }
}

test('no customization keeps the full catalogue in default order', () => {
  assert.deepEqual(splitEntries(keys, null), { visible: keys, hidden: [] })
})
test('custom layout splits visible and tucked entries, ignoring unknown and duplicate keys', () => {
  assert.deepEqual(splitEntries(keys, ['D', 'A', 'GONE', 'D']), { visible: ['D', 'A'], hidden: ['B', 'C'] })
})
test('visible entries are capped at twelve; extras stay tucked in catalogue order', () => {
  const many = Array.from({ length: WORKBENCH_MAX_ENTRIES + 3 }, (_, index) => `T${index}`)
  const { visible, hidden } = splitEntries([...many, 'EXTRA'], many)
  assert.equal(visible.length, WORKBENCH_MAX_ENTRIES)
  assert.deepEqual(visible, many.slice(0, WORKBENCH_MAX_ENTRIES))
  assert.deepEqual(hidden, ['T12', 'T13', 'T14', 'EXTRA'])
})
test('layout roundtrips through storage; corrupt or malformed records fall back to default', () => {
  const storage = fakeStorage()
  assert.equal(loadWorkbenchLayout(storage), null)
  saveWorkbenchLayout(storage, ['A', 'B'])
  assert.deepEqual(loadWorkbenchLayout(storage), ['A', 'B'])
  storage.setItem('ocr-workbench-entries-v1', '{broken')
  assert.equal(loadWorkbenchLayout(storage), null)
  storage.setItem('ocr-workbench-entries-v1', '["A",5]')
  assert.equal(loadWorkbenchLayout(storage), null)
  assert.equal(loadWorkbenchLayout(null), null)
})
test('saving null clears the stored customization', () => {
  const storage = fakeStorage({ 'ocr-workbench-entries-v1': '["A"]' })
  saveWorkbenchLayout(storage, null)
  assert.equal(loadWorkbenchLayout(storage), null)
})
test('storage failures while saving are swallowed', () => {
  saveWorkbenchLayout({ getItem: () => null, setItem: () => { throw new Error('quota') }, removeItem: () => {} }, ['A'])
})
