import test from 'node:test'
import assert from 'node:assert/strict'
import { WORKBENCH_MAX_ENTRIES, parseWorkbenchLayout, parseWorkbenchPreferences, splitEntries } from '../src/workbenchEntries.ts'

const keys = ['A', 'B', 'C', 'D']
test('a small default catalogue keeps its order', () => {
  assert.deepEqual(splitEntries(keys, null), { visible: keys, hidden: [] })
})
test('custom layout splits visible and tucked entries, ignoring unknown and duplicate keys', () => {
  assert.deepEqual(splitEntries(keys, ['D', 'A', 'GONE', 'D']), { visible: ['D', 'A'], hidden: ['B', 'C'] })
})
test('default and custom layouts show at most twelve; excess types stay accessible', () => {
  const many = Array.from({ length: WORKBENCH_MAX_ENTRIES + 3 }, (_, index) => `T${index}`)
  const { visible, hidden } = splitEntries([...many, 'EXTRA'], many)
  assert.equal(visible.length, WORKBENCH_MAX_ENTRIES)
  assert.deepEqual(visible, many.slice(0, WORKBENCH_MAX_ENTRIES))
  assert.deepEqual(hidden, ['T12', 'T13', 'T14', 'EXTRA'])
  assert.deepEqual(splitEntries([...many, 'EXTRA'], null), { visible, hidden })
  assert.equal(WORKBENCH_MAX_ENTRIES, 12)
})

test('legacy thirteen-key saved preferences remain readable and tuck the last card', () => {
  const catalogue = Array.from({ length: 13 }, (_, index) => String.fromCharCode(65 + index))
  const saved = parseWorkbenchLayout({ layout: catalogue, revision: 7 })
  assert.deepEqual(saved.layout, catalogue)
  assert.equal(saved.revision, 7)
  assert.deepEqual(splitEntries(catalogue, saved.layout), { visible: catalogue.slice(0, 12), hidden: ['M'] })
  const expanded = [...catalogue, 'N']
  assert.deepEqual(parseWorkbenchLayout({ layout: expanded, revision: 7 }).layout, expanded)
  assert.equal(splitEntries(expanded, expanded).visible.length, 12)
  assert.throws(() => parseWorkbenchLayout({ layout: [...expanded, 'O'], revision: 7 }))
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
