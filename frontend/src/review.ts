import type { TaskResult, ReviewIssue, Task, Field, ReportSummary } from './business.ts'
import { docTypes, isMedicalReviewItem } from './business.ts'
import { formatTime } from './presentation.ts'
import type { TableDraft } from './table-review.ts'
import type { GenericDraft } from './generic-review.ts'
export type AbsenceReason = 'NOT_ON_DOCUMENT' | 'NOT_APPLICABLE'
export type Scalar = string | number | boolean | null
export interface ReviewBody {
  run_id: string; expected_revision: number; fields?: Record<string, Scalar>;
  absence_reasons?: Record<string, AbsenceReason>; accepted_issues?: { issue_id: string; reason?: string }[];
  confirmed_disputes?: string[];
  confirm_export_disputes?: boolean;
  items?: Record<string, unknown>[]; added_items?: Record<string, unknown>[]; removed_item_ids?: string[];
  findings?: Record<string, unknown>[]; members?: { index: number; fields: Record<string, Scalar>; absence_reasons?: Record<string, AbsenceReason> }[];
  added_members?: { fields: Record<string, Scalar>; source_page: number }[]; removed_member_indexes?: number[]; added_member_indexes?: number[];
  generic?: GenericDraft;
  coverage?: { pages: number[]; reason: string; regions?: { region_id: string; action: 'TRANSCRIBED' | 'NO_CONTENT'; item_ids?: string[]; field_keys?: string[]; added_item_indexes?: number[]; finding_ids?: string[]; member_indexes?: number[]; added_member_indexes?: number[]; generic?: boolean; reason: string }[] };
  report_summary?: { declared_count?: number | null; scope?: ReportSummary['scope']; title?: string; reason: string; source_page: number; added_findings?: Record<string, unknown>[]; removed_finding_ids?: string[] };
  note?: string;
  tables?: TableDraft[];
}
export type ReviewDraft = Omit<ReviewBody, 'run_id' | 'expected_revision'>
export const canAcceptIssue = (issue: ReviewIssue) => issue.can_accept === true && !['MISSING','CONFLICT','INCOMPLETE_OUTPUT','MULTI_CANDIDATES','LOW_CONFIDENCE'].includes(issue.code) &&
  (issue.code !== 'VALIDATION_FAILED' || issue.rule_id?.startsWith('bin_reference_') === true)
export function collectIssues(result: TaskResult): { scope: string; issue: ReviewIssue }[] {
  const rows: { scope: string; issue: ReviewIssue }[] = []
  const append = (scope: string, issues?: ReviewIssue[]) => issues?.forEach(issue => rows.push({ scope, issue }))
  append('任务', result.review_issues)
  for (const field of result.fields ?? Object.values(result.basic_info ?? {})) append(field.label, field.review_issues)
  for (const item of result.items ?? []) if (isMedicalReviewItem(item)) append(`项目：${item.name}`, item.review_issues)
  for (const [index, finding] of (result.report_summary?.findings ?? []).entries()) append(`清单 ${index + 1}`, finding.review_issues)
  for (const [index, member] of (result.members ?? []).entries()) for (const field of memberFields(member)) append(`成员 ${index + 1} / ${field.label}`, field.review_issues)
  return rows.filter((row, i) => rows.findIndex(other => other.issue.issue_id === row.issue.issue_id) === i)
}
export const looksMasked = (value: unknown) => typeof value === 'string' && /[*＊•●]{2,}/.test(value)
export function memberFields(member: Record<string, unknown>): Field[] {
  return Object.entries(member).filter(([key]) => key !== 'member_id' && key !== 'source_page').map(([,value]) => value as Field)
}
export function addedMember(fields: Record<string, Scalar>, page: number, pageCount: number, requiredKeys: readonly string[] = ['name']) {
  if (!Number.isInteger(page) || page < 1 || page > pageCount || requiredKeys.some(key => fields[key] == null || typeof fields[key] === 'string' && !fields[key].trim())) throw new Error('MEMBER_SOURCE')
  return { fields: changedValues({}, fields) as Record<string, Scalar>, source_page: page }
}
export function summaryPatch(original: ReportSummary | undefined, scope: ReportSummary['scope'], count: number | undefined, title: string, reason: string, page: number, pageCount: number): NonNullable<ReviewBody['report_summary']> {
  if (!reason.trim() || !Number.isInteger(page) || page < 1 || page > pageCount) throw new Error('SUMMARY_SOURCE')
  const result: NonNullable<ReviewBody['report_summary']> = { scope, reason, source_page: page }
  const nextCount = scope === 'follow_up_required' ? count ?? null : null
  if (nextCount !== null && (!Number.isInteger(nextCount) || nextCount < 0)) throw new Error('SUMMARY_COUNT')
  if (nextCount !== (original?.declared_count ?? null)) result.declared_count = nextCount
  if (scope === 'follow_up_required' && (scope !== original?.scope || Object.hasOwn(result,'declared_count'))) {
    if (!title.trim()) throw new Error('SUMMARY_TITLE')
    result.title = title.trim()
  }
  return result
}
export function changedValues(original: Record<string, unknown>, proposed: Record<string, unknown>): Record<string, unknown> {
  const changes: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(proposed)) {
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('INVALID_NUMBER')
    if (value === original[key] || (value === '' && original[key] == null)) continue
    if (looksMasked(value)) throw new Error('MASKED_VALUE')
    changes[key] = value === '' ? null : value
  }
  return changes
}
export function buildReview(result: TaskResult, draft: ReviewDraft): ReviewBody {
  const body: ReviewBody = { ...draft, run_id: result.run_id, expected_revision: result.result_revision }
  if (draft.fields) {
    const original = Object.fromEntries((result.fields ?? Object.values(result.basic_info ?? {})).map(f => [f.key, f.value]))
    body.fields = changedValues(original, draft.fields) as Record<string, Scalar>
    for (const key of Object.keys(draft.absence_reasons ?? {})) {
      if (Object.hasOwn(body.fields, key) && body.fields[key] !== null) throw new Error('CONFLICTING_ABSENCE')
      delete body.fields[key]
    }
    if (!Object.keys(body.fields).length) delete body.fields
  }
  if (draft.accepted_issues) {
    const issues = collectIssues(result)
    for (const accepted of draft.accepted_issues) if (!issues.some(row => row.issue.issue_id === accepted.issue_id && canAcceptIssue(row.issue))) throw new Error('INVALID_ACCEPTANCE')
    body.accepted_issues = draft.accepted_issues.map(accepted => ({ issue_id: accepted.issue_id, ...(accepted.reason?.trim() ? {reason:accepted.reason.trim()} : {}) }))
  }
  return body
}
export function exportBlockReason(tasks: readonly Pick<Task, 'status' | 'export_ready'>[]): string | null {
  if (!tasks.length) return '请先选择需要导出的任务。'
  const missing = tasks.filter(t => t.export_ready === false).length
  return missing ? `有 ${missing} 个任务尚不能导出：必填未填、识别有异议、结果未生成，或表格结构及完整性需处理。请在任务详情中改正后点击「保存修正」，保存成功后即可导出。` : null
}
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function spreadsheetName(types: readonly (string | undefined)[], at = new Date(), personPackage = false): string {
  const labels = new Set(types.map(type => type && Object.hasOwn(docTypes, type) ? docTypes[type as keyof typeof docTypes] : '识别结果'))
  const stamp = formatTime(at.toISOString()).replace(/\D/g, '')
  return `${personPackage ? '人员材料包' : [...labels].join('+') || '识别结果'}_${stamp.slice(0, 8)}_${stamp.slice(8)}.xlsx`
}
