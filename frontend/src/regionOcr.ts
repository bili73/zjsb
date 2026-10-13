import { isRecord } from './business.ts'
import type { Task } from './business.ts'

export type RegionBox = [number, number, number, number]
export interface RegionText { text: string; confidence: number }
export interface DateCopySuggestion { raw: string; value: string }

export function dateCopySuggestions(text: string): DateCopySuggestion[] {
  const digits = '0-9０-９〇○零一二三四五六七八九'
  const yearDigits = digits + 'Oo'
  const part = `[${digits}十](?:\\s*[${digits}十]){0,2}`
  // Like certificate footers, a complete day may omit 日 at an unambiguous boundary.
  const dayEnd = '\\s*日|(?=[ \\t　]*(?:$|[（）()，,。；;：:至到\\-—–~～]|\\r?\\n))'
  const pattern = new RegExp(`(?<![${yearDigits}十百千万])((?:[${yearDigits}]\\s*){4})年\\s*(${part})\\s*月(?:\\s*(${part})(?:${dayEnd}))?`, 'g')
  const nextDate = new RegExp(`^\\s*(?:[${yearDigits}]\\s*){4}年`)
  const incompleteDay = new RegExp(`^\\s*[${digits}十日a-zA-Z?？□■*＊×_廿卅壹贰貳叁參肆伍陆陸柒捌玖拾百千万]`)
  const values: Record<string, string> = { '〇': '0', '○': '0', '零': '0', '一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9' }
  function number(raw: string) {
    const value = raw.replace(/\s/g, '').replace(/[Oo]/g, '0').replace(/[０-９]/g, c => String(c.charCodeAt(0) - 0xff10))
      .replace(/[〇○零一二三四五六七八九]/g, c => values[c]!)
    if (/^\d+$/.test(value)) return Number(value)
    const tens = /^(\d?)十(\d?)$/.exec(value)
    return tens ? Number(tens[1] || 1) * 10 + Number(tens[2] || 0) : NaN
  }
  const suggestions: DateCopySuggestion[] = [], seen = new Set<string>()
  for (const match of text.matchAll(pattern)) {
    if (!match[3]) {
      const tail = text.slice(match.index + match[0].length)
      // Visible but incomplete day tokens cannot be dropped to invent month precision.
      if (!nextDate.test(tail) && incompleteDay.test(tail)) continue
    }
    const year = number(match[1]!), month = number(match[2]!), day = match[3] ? number(match[3]) : null
    if (!(year >= 1 && year <= 9999 && month >= 1 && month <= 12)) continue
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]!
    if (day !== null && !(day >= 1 && day <= days)) continue
    const value = `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}` + (day === null ? '' : `-${String(day).padStart(2, '0')}`)
    if (!seen.has(value)) { seen.add(value); suggestions.push({ raw: match[0], value }) }
  }
  return suggestions
}

export function pointInImage(x: number, y: number, rect: { left: number; top: number; width: number; height: number }) {
  if (rect.width <= 0 || rect.height <= 0) throw new Error('IMAGE_NOT_READY')
  return { x: Math.max(0, Math.min(1, (x - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (y - rect.top) / rect.height)) }
}
export function regionBox(a: { x: number; y: number }, b: { x: number; y: number }): RegionBox {
  return [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)]
}
export function parseRegionText(value: unknown, task: Task, field: string | null, page: number, bbox: RegionBox): RegionText {
  if (!isRecord(value) || value.task_id !== task.task_id || value.run_id !== task.run_id || value.result_revision !== task.result_revision ||
      value.field_key !== field || value.page !== page || !Array.isArray(value.bbox) || value.bbox.length !== 4 ||
      value.bbox.some((v, index) => v !== bbox[index]) || typeof value.text !== 'string' || !value.text.trim() || value.text.length > 4096 ||
      typeof value.confidence !== 'number' || !Number.isFinite(value.confidence) || value.confidence < 0 || value.confidence > 1) throw new Error('INVALID_RESPONSE')
  return { text: value.text, confidence: value.confidence }
}

export function mostVisiblePage(pages: { page: number; top: number; bottom: number }[], top: number, bottom: number, fallback: number) {
  let selected = fallback, area = 0
  for (const page of pages) {
    const visible = Math.max(0, Math.min(bottom, page.bottom) - Math.max(top, page.top))
    if (visible > area || visible > 0 && visible === area && page.page === fallback) { selected = page.page; area = visible }
  }
  return selected
}
