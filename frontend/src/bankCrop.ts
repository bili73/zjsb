// Exact quarter turns keep display pixels and crop pixels in one coordinate space.
export function quarterTurn(width: number, height: number, direction: 1 | -1) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) throw new Error('IMAGE_NOT_READY')
  const transform: [number,number,number,number,number,number] = direction === 1 ? [0,1,-1,0,height,0] : [0,-1,1,0,0,width]
  return { width:height, height:width, transform }
}
import type { TaskResult } from './business.ts'

export function needsBankCrop(result: TaskResult): boolean {
  if (result.doc_type !== 'BANK_CARD') return false
  const card = result.fields?.find(field => field.key === 'card_number')
  if (card?.value == null || String(card.value).trim() === '') return true
  return card.review_issues.some(issue => issue.code === 'CONFLICT' || issue.code === 'MISSING' ||
    issue.code === 'VALIDATION_FAILED' && !issue.can_accept)
}
