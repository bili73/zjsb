import test from 'node:test'
import assert from 'node:assert/strict'
import { WORKBENCH_MAX_ENTRIES, parseWorkbenchLayout, parseWorkbenchPreferences, splitEntries } from '../src/workbenchEntries.ts'

const keys = ['A', 'B', 'C', 'D']
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
test('server contracts distinguish defaults from all tucked and reject malformed data', () => {
  for (const layout of [null, [], ['TABLE', 'BANK_CARD']]) {
    assert.deepEqual(parseWorkbenchLayout({ layout, revision: 3 }), { layout, revision: 3 })
  }
  assert.deepEqual(splitEntries(keys, []), { visible: [], hidden: keys })
  for (const value of [null, {}, { layout: null, revision: -1 }, { layout: [], revision: true },
    { layout: [3], revision: 1 }, { layout: ['TABLE', 'TABLE'], revision: 1 },
    { layout: ['<script>'], revision: 1 }, { layout: [], revision: 1, user_id: 'forged' }]) {
    assert.throws(() => parseWorkbenchLayout(value))
  }
  assert.deepEqual(parseWorkbenchPreferences({layout:null, revision:0, defaults:{layout:['TABLE'], revision:2}}),
    {layout:null, revision:0, defaults:{layout:['TABLE'], revision:2}})
  for (const defaults of [undefined, null, {}, {layout:['TABLE','TABLE'], revision:0}]) {
    assert.throws(() => parseWorkbenchPreferences({layout:null, revision:0, defaults}))
  }
})
