import test from 'node:test'
import assert from 'node:assert/strict'
import { medicalProjectCount } from '../src/business.ts'

test('ledger count uses catalogue entries, retaining combined names and abstaining on missing input', () => {
  assert.equal(medicalProjectCount('身高体重血压；尿常规；DR胸部正位检查'), 3)
  assert.equal(medicalProjectCount('内科检查; 尿常规\n尿常规；心电图'), 3)
  assert.equal(medicalProjectCount('检查甲、检查乙；项目丙'), 2)
  assert.equal(medicalProjectCount('； \n;'), null)
  assert.equal(medicalProjectCount(null), null)
})
