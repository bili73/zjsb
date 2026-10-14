import test from 'node:test'
import assert from 'node:assert/strict'
import { parseResult } from '../src/business.ts'

test('bank candidates retain role labels and reject invalid source coordinates', () => {
  const source = { page: 1, region_id: '11111111-2222-4333-8444-555555555555', bbox: [0, .2, 1, .4], raw_text: '4111111111111111', extraction_method: 'ocr' }
  const candidate = { value: '4111111111111111', reason: '卡面识别', source }
  const result = { task_id: source.region_id, run_id: source.region_id, result_revision: 1, doc_type: 'BANK_CARD', status: 'NEED_REVIEW', review_issues: [], fields: [{ key: 'card_number', label: '卡号', value: null, confidence: null, confidence_method: 'unavailable', need_review: true, review_issues: [], candidates: [candidate] }] }
  assert.equal(parseResult(result).fields?.[0]?.candidates?.[0]?.source?.raw_text, candidate.value)
  assert.throws(() => parseResult({ ...result, fields: [{ ...result.fields[0], candidates: [{ ...candidate, source: { ...source, bbox: [0, 0, 2, 1] } }] }] }), /INVALID_RESPONSE/)
})
