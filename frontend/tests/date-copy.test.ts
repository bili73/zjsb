import test from 'node:test'
import assert from 'node:assert/strict'
import { dateCopySuggestions } from '../src/regionOcr.ts'

test('Chinese dates preserve source and calendar precision', () => {
  for (const [raw, value] of [
    ['2024年6月', '2024-06'], ['2024年6月30日', '2024-06-30'],
    ['二〇二四年六月三十日', '2024-06-30'], ['二零二四年十二月', '2024-12'],
    ['二○二四年一月一日', '2024-01-01'], ['２０２４年０６月０９日', '2024-06-09'],
    ['2 0 2 4 年 6 月 3 0 日', '2024-06-30'], ['二〇二四 年 十 二 月 二 十 九 日', '2024-12-29'],
    ['2024年6月\n30日', '2024-06-30'], ['2000年2月29日', '2000-02-29'],
    ['2024年6月30', '2024-06-30'], ['二〇二五年 六 月 十九', '2025-06-19'],
    ['2024年6月三', '2024-06-03'], ['二O二五年 六月 十九 日', '2025-06-19'],
    ['202O年6月', '2020-06'],
  ]) assert.deepEqual(dateCopySuggestions(raw), [{ raw, value }], raw)
})

test('ranges and separate dates keep order without choosing a document role', () => {
  const text = '入学：2018年9月 至 2022年6月30日毕业\n落款：二〇二二年七月一日';
  assert.deepEqual(dateCopySuggestions(text), [
    { raw: '2018年9月', value: '2018-09' }, { raw: '2022年6月30日', value: '2022-06-30' },
    { raw: '二〇二二年七月一日', value: '2022-07-01' },
  ])
  assert.deepEqual(dateCopySuggestions('2024年6月\n2024年7月').map(d => d.value), ['2024-06', '2024-07'])
  assert.deepEqual(dateCopySuggestions('2024年6月，二〇二四年六月，2024年06月30日').map(d => d.value), ['2024-06', '2024-06-30'])
  assert.deepEqual(dateCopySuggestions('（2025年6月19）。').map(d => d.value), ['2025-06-19'])
  assert.deepEqual(dateCopySuggestions('2024年6月30至2025年7月1').map(d => d.value), ['2024-06-30', '2025-07-01'])
})

test('invalid or incomplete dates cannot silently become month-only suggestions', () => {
  for (const text of ['2023年2月29日', '1900年2月29日', '2024年4月31日', '2024年0月',
    '2024年13月', '2024年6月0日', '2024年6月32日', '2024年6月0', '2024年6月32',
    '2024年6月X日', '2024年6月日', '2024年6月?日', '2024年6月30?', '2024年6月300日',
    '2024年6月**日', '2024年6月廿五日', '2024年6月贰拾日', '2024年6月\nX日',
    '2024年6月1*', '2025年6月19 未知说明', '2024年2月30',
    '2024年', '24年6月', '12024年6月', '二〇二四年十十月',
    '0000年1月1日', '证书编号20240630', '', '普通原文', '2024-06-30']) {
    assert.deepEqual(dateCopySuggestions(text), [], text)
  }
  assert.deepEqual(dateCopySuggestions('错误2023年2月30日，正确2024年2月29日'), [
    { raw: '2024年2月29日', value: '2024-02-29' },
  ])
})
