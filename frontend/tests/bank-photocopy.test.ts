import test from 'node:test'
import assert from 'node:assert/strict'
import { docTypes, parseCatalogue, parseClassification, parseResult } from '../src/business.ts'
import { numberLengthHint } from '../src/numberLength.ts'

test('bank candidates retain role labels and reject invalid source coordinates', () => {
  const source = { page: 1, region_id: '11111111-2222-4333-8444-555555555555', bbox: [0, .2, 1, .4], raw_text: '4111111111111111', extraction_method: 'ocr' }
  const candidate = { value: '4111111111111111', reason: '卡面识别', source }
  const result = { task_id: source.region_id, run_id: source.region_id, result_revision: 1, doc_type: 'BANK_CARD', status: 'NEED_REVIEW', review_issues: [], fields: [{ key: 'card_number', label: '卡号', value: null, confidence: null, confidence_method: 'unavailable', need_review: true, review_issues: [], candidates: [candidate] }] }
  assert.equal(parseResult(result).fields?.[0]?.candidates?.[0]?.source?.raw_text, candidate.value)
  assert.equal(parseResult({ ...result, doc_type: 'BANK_CARD_COPY' }).doc_type, 'BANK_CARD_COPY')
  assert.throws(() => parseResult({ ...result, fields: [{ ...result.fields[0], candidates: [{ ...candidate, source: { ...source, bbox: [0, 0, 2, 1] } }] }] }), /INVALID_RESPONSE/)
})

test('copy catalogue, editable suggestions and PAN warnings retain their business type', () => {
  assert.equal(docTypes.BANK_CARD_COPY, '银行卡复印件')
  const fields = ['holder_name', 'card_number', 'bank_name', 'branch_name'].map(key => ({ key, label: key, required: true }))
  assert.equal(parseCatalogue([{ doc_type: 'BANK_CARD_COPY', label: '银行卡复印件', fields }])[0]?.fields.length, 4)
  assert.equal(parseClassification({ doc_type: 'BANK_CARD_COPY', basis: 'content', candidates: ['BANK_CARD_COPY'], reason: '请核对' }).doc_type, 'BANK_CARD_COPY')
  assert.equal(parseClassification({ doc_type: null, basis: 'unknown', candidates: ['BANK_CARD', 'BANK_CARD_COPY'], reason: '请选择' }).doc_type, null)
  const invalid = '1'.repeat(20)
  assert.deepEqual(numberLengthHint('BANK_CARD_COPY', 'card_number', invalid), numberLengthHint('BANK_CARD', 'card_number', invalid))
  assert.equal(numberLengthHint('BANK_CARD_COPY', 'card_number', invalid)?.level, 'warning')
})
