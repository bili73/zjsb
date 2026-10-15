import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { numberLengthHint } from '../src/numberLength.ts'
import { bankLengthReference, bankLengthSourceHash } from '../src/bankLengthReference.ts'

test('generated card reference matches the pinned source including ambiguous products', () => {
  const raw = readFileSync(new URL('../../backend/ocr_app/data/bank_bins/bin.csv', import.meta.url))
  assert.equal(createHash('sha256').update(raw).digest('hex'), bankLengthSourceHash)
  const grouped = new Map<string, { products: Set<string>; lengths: Set<number> }>()
  for (const line of raw.toString('utf8').trim().split(/\r?\n/).slice(1)) {
    const [prefix, bank, type, length] = line.split(',')
    const group = grouped.get(prefix!) ?? { products: new Set(), lengths: new Set() }
    group.products.add(`${bank}/${type}`); group.lengths.add(Number(length)); grouped.set(prefix!, group)
  }
  const expected = Object.fromEntries([...grouped].map(([prefix, group]) => [prefix,
    group.products.size === 1 ? [...group.lengths].sort((a, b) => a - b) : null]))
  assert.deepEqual(bankLengthReference, expected)
})

test('ID and credit-code hints remain fixed-length and do not validate authenticity', () => {
  assert.match(numberLengthHint('INTERVIEW_FORM', 'id_number', '110105194912310002X')!.message, /19位，比18位多1位/)
  assert.equal(numberLengthHint('ID_CARD_FRONT', 'id_number', '11010519491231002x'), null)
  assert.equal(numberLengthHint('ID_CARD_FRONT', 'id_number', '110105194912310021'), null)
  assert.match(numberLengthHint('BUSINESS_LICENSE', 'unified_social_credit_code', '9'.repeat(17))!.message, /少1位/)
  assert.equal(numberLengthHint('BUSINESS_LICENSE', 'unified_social_credit_code', '9'.repeat(18)), null)
})

test('bank hints use a covered prefix and keep original grouped/full-width text', () => {
  const original = '６２１７ ８５００-００００ ００００ ００'
  const hint = numberLengthHint('BANK_CARD', 'card_number', original)!
  assert.equal(hint.level, 'warning'); assert.match(hint.message, /18位/)
  assert.match(hint.message, /19位/); assert.match(hint.message, /少1位/)
  assert.match(hint.message, /离线/); assert.match(hint.message, /可能过时/)
  assert.equal(original, '６２１７ ８５００-００００ ００００ ００')
  assert.equal(numberLengthHint('BANK_CARD', 'card_number', '621785' + '0'.repeat(13)), null)
})

test('unknown and unsupported longer card prefixes never borrow a shorter rule', () => {
  assert.equal(numberLengthHint('BANK_CARD', 'card_number', '000000' + '0'.repeat(12))!.level, 'info')
  assert.match(numberLengthHint('BANK_CARD', 'card_number', '9'.repeat(20))!.message, /10–19/)
  const prefix = Object.keys(bankLengthReference).find(prefix => prefix.length > 8 &&
    Object.keys(bankLengthReference).some(shorter => shorter.length === 6 && prefix.startsWith(shorter)))!
  const number = prefix.padEnd(19, '0')
  assert.equal(numberLengthHint('BANK_CARD', 'card_number', number)!.level, 'info')
  const ambiguous = Object.keys(bankLengthReference).find(prefix => bankLengthReference[prefix] === null)
  if (ambiguous) assert.equal(numberLengthHint('BANK_CARD', 'card_number', ambiguous.padEnd(19, '0'))!.level, 'info')
})

test('diplomas and Xuexin certificates keep leading zeros and historical exceptions', () => {
  for (const type of ['DIPLOMA', 'XUEXIN_DIPLOMA_TABLE']) {
    for (const length of [17, 18]) assert.equal(numberLengthHint(type, 'certificate_no', '0'.repeat(length)), null)
    assert.equal(numberLengthHint(type, 'certificate_no', '000123')!.level, 'info')
    assert.match(numberLengthHint(type, 'certificate_no', '0'.repeat(19))!.message, /常见17或18位/)
    assert.equal(numberLengthHint(type, 'certificate_no', '0'.repeat(19))!.level, 'warning')
  }
})

test('degree hints distinguish ordinary lengths from historical T/Z prefixes', () => {
  for (const prefix of ['', 'T', 'Z', 't']) {
    assert.equal(numberLengthHint('DEGREE_CERT', 'certificate_no', prefix + '0'.repeat(16)), null)
  }
  assert.equal(numberLengthHint('DEGREE_CERT', 'certificate_no', '0'.repeat(14))!.level, 'info')
  assert.match(numberLengthHint('DEGREE_CERT', 'certificate_no', 'T' + '0'.repeat(17))!.message, /17位/)
  assert.equal(numberLengthHint('DEGREE_CERT', 'certificate_no', '0'.repeat(17))!.level, 'warning')
})

test('online codes use existing compatibility rules; missing and unsupported fields stay quiet', () => {
  for (const length of [12, 16]) assert.equal(numberLengthHint('XUEXIN_DIPLOMA_TABLE', 'online_verification_code', 'A'.repeat(length)), null)
  assert.match(numberLengthHint('XUEXIN_DIPLOMA_TABLE', 'online_verification_code', 'A'.repeat(13))!.message, /12或16位/)
  for (const value of [null, undefined, '', ' \n ']) assert.equal(numberLengthHint('BANK_CARD', 'card_number', value), null)
  assert.equal(numberLengthHint('PASSPORT', 'passport_number', 'ABC123'), null)
  assert.equal(numberLengthHint('GENERIC', 'certificate_no', '123'), null)
})
