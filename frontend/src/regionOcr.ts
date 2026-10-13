import { isRecord } from './business.ts'
import type { Task } from './business.ts'

export type RegionBox = [number, number, number, number]
export interface RegionText { text: string; confidence: number }

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
