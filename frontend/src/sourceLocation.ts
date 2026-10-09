import type { FieldSource } from './business.ts'

export function sourceSelection(source: FieldSource): FieldSource {
  return { ...source, page: source.page ?? 1, ...(source.bbox ? { bbox: [...source.bbox] as [number, number, number, number] } : {}) }
}
