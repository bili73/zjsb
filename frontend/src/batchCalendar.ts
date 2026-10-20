import { formatTime } from './presentation.ts'
import type { BatchEntry } from './monitor.ts'

export type BatchPeriod = 'day' | 'week' | 'month'
export interface BatchDateRange { date_from: string; date_to: string }
type Entry = { id: string; entry: BatchEntry }

export function periodBounds(anchor: string | null, period: BatchPeriod): BatchDateRange | null {
  if (!anchor || !/^\d{4}-\d{2}-\d{2}$/.test(anchor)) return null
  const start = new Date(`${anchor}T00:00:00Z`)
  if (!Number.isFinite(start.getTime()) || start.toISOString().slice(0, 10) !== anchor) return null
  if (period === 'week') start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7)
  if (period === 'month') start.setUTCDate(1)
  const end = new Date(start)
  if (period === 'week') end.setUTCDate(end.getUTCDate() + 6)
  if (period === 'month') { end.setUTCMonth(end.getUTCMonth() + 1); end.setUTCDate(0) }
  return { date_from: start.toISOString().slice(0, 10), date_to: end.toISOString().slice(0, 10) }
}

export function groupBatchEntries(entries: readonly Entry[], period: BatchPeriod) {
  const stamp = (item: Entry) => {
    const iso = item.entry.batch?.created_at
    const value = Date.parse(iso ?? '')
    return Number.isFinite(value) ? value : item.entry.batch ? -Infinity : Infinity
  }
  const groups = new Map<string, { key: string; label: string; entries: Entry[] }>()
  const sorted = [...entries].sort((a, b) => stamp(a) === stamp(b) ? 0 : stamp(a) > stamp(b) ? -1 : 1)
  for (const item of sorted) {
    const iso = item.entry.batch?.created_at
    const bounds = periodBounds(formatTime(iso).slice(0, 10), period)
    const key = bounds ? `${period}:${bounds.date_from}` : item.entry.batch ? 'unknown' : 'pending'
    const label = bounds ? period === 'month' ? bounds.date_from.slice(0, 7).replace('-', '年') + '月'
      : period === 'week' ? `${bounds.date_from} 至 ${bounds.date_to}` : bounds.date_from
      : item.entry.batch ? '创建时间未知' : '新批次 · 正在同步'
    if (!groups.has(key)) groups.set(key, { key, label, entries: [] })
    groups.get(key)!.entries.push(item)
  }
  return [...groups.values()]
}

// 时间范围括注：周语义只在周视图成立；日/月视图与未锚定（全部日期）时只标注时区。
export function rangeSuffix(period: BatchPeriod, anchored: boolean): string {
  return anchored && period === 'week' ? '（UTC+8，周一至周日）' : '（UTC+8）'
}
