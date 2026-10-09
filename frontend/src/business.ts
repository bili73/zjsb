import { safeCode, safeId, safeStage } from './diagnostics.ts'
import type { ErrorCode, Stage } from './diagnostics.ts'

export const docTypes = {
  MEDICAL_REPORT: '体检报告', DIPLOMA: '毕业证', DEGREE_CERT: '学位证',
  BANK_CARD: '银行卡', ID_CARD_FRONT: '身份证人像面', ID_CARD_BACK: '身份证国徽面', PASSPORT: '护照',
  HOUSEHOLD_REGISTER: '户口本', BUSINESS_LICENSE: '营业执照', GENERIC: '通用识别', XUEXIN_DIPLOMA_TABLE: '学历证书电子注册备案表',
} as const
export type UploadDocType = keyof typeof docTypes
export interface CatalogueField { key: string; label: string; required?: boolean; editable?: boolean; type?: string; required_when?: unknown }
export interface DocProfile { doc_type: UploadDocType; label: string; fields: CatalogueField[] }
export function parseCatalogue(value: unknown): DocProfile[] {
  requireValue(Array.isArray(value) && value.length > 0 && value.every(p => isRecord(p) && typeof p.doc_type === 'string' && Object.hasOwn(docTypes, p.doc_type) && typeof p.label === 'string' && Array.isArray(p.fields) && p.fields.every(f => isRecord(f) && typeof f.key === 'string' && typeof f.label === 'string')))
  return value as DocProfile[]
}
export const taskLabels = { QUEUED: '排队中', PREPROCESSING: '预处理中', OCR: '识别中', EXTRACTING: '整理中', VALIDATING: '校验中', NEED_REVIEW: '待人工核对', COMPLETED: '已完成', FAILED: '处理失败', REJECTED: '已拒绝', CANCELLED: '已取消' } as const
export type TaskStatus = keyof typeof taskLabels
export const batchLabels = { PROCESSING: '处理中 / 待核对', COMPLETED: '已完成', PARTIAL: '部分完成', FAILED: '处理失败', CANCELLED: '已取消' } as const
export type BatchStatus = keyof typeof batchLabels
export interface User { user_id: string; display_name: string; role: 'viewer' | 'operator' | 'admin'; permissions: string[]; csrf_token?: string }
export interface ManagedUser { user_id: string; username: string; display_name: string; role: User['role']; enabled: boolean }
export interface Batch { batch_id: string; display_name?: string; status: BatchStatus; file_count?: number; completed_count?: number; need_review_count?: number; failed_count?: number; created_at?: string }
export interface BatchList { items: Batch[]; total: number; page: number; page_size: number }
export interface TaskError { code: ErrorCode; error_id: string | null; stage: Stage | null }
export interface ExportEligibility { export_ready?: boolean; export_blockers?: { field: string; code: string }[] }
export interface Task extends ExportEligibility { task_id: string; batch_id?: string; run_id: string; result_revision: number; cancel_requested: boolean; status: TaskStatus; file_name?: string; doc_type?: string; progress?: number; page_count: number; actual_source_page_count?: number; content_hash?: string; pages: { page_id: string; page_index: number; extraction_method: string; regions?: { region_id: string }[] }[]; error?: TaskError | null; extract_options?: { abnormal_only?: boolean } }
export type ItemsFilter = 'all' | 'abnormal' | 'unknown'
export interface ReviewIssue { issue_id: string; code: string; message: string; can_accept: boolean }
export interface FieldSource { page?: number; region_id?: string; extraction_method?: 'pdf_text' | 'ocr'; bbox?: [number, number, number, number]; bbox_kind?: 'region' | 'block' | 'row' | 'cell'; raw_text?: string }
export interface ReportFinding { finding_id: string; reported_number: string | null; text: string; sources: FieldSource[]; project_name?: string | null; result_item_id?: string | null; risk_grade?: string | null; diagnosis?: string | null; result_raw?: string | null; result_sources?: FieldSource[]; need_review?: boolean; review_issues?: ReviewIssue[] }
export interface ReportSummary { scope: 'follow_up_required' | 'overall_conclusion' | 'unidentified'; declared_count: number | null; findings: ReportFinding[]; count_check: 'match' | 'mismatch' | 'unverified'; sources: FieldSource[] }
export interface Field { key: string; label: string; value: string | number | boolean | null; value_masked?: string | null; confidence: number | null; confidence_method: 'calibrated' | 'unavailable'; need_review: boolean; review_issues: ReviewIssue[]; source?: FieldSource; sources?: FieldSource[]; required?: boolean; editable?: boolean; absence_reason?: string }
export function fieldValueText(field: Field, medical = false): string {
  if (field.value !== null && field.value !== undefined) {
    return isGenderKey(field.key) ? genderText(field.value) || '未识别' : String(field.value)
  }
  if (field.absence_reason === 'NOT_ON_DOCUMENT') return medical ? '报告未载明' : '未载明'
  if (field.absence_reason === 'NOT_APPLICABLE') return '不适用'
  return '未识别'
}
export type AbnormalBasis = 'report_marker' | 'report_grade' | 'reference_comparison' | 'unknown'
export type AbnormalFlag = 'NORMAL' | 'HIGH' | 'LOW' | 'ABNORMAL' | 'POSITIVE' | 'UNKNOWN'
export function medicalProjectCount(value: unknown): number | null {
  if (typeof value !== 'string') return null
  const names = new Set(value.split(/[；;\n]+/).map(v => v.trim()).filter(Boolean))
  return names.size || null
}
export interface MedicalItem { item_id: string; name: string; alias?: string | null; category?: string | null; result_raw: string; risk_grade?: string | null; diagnosis?: string | null; diagnosis_sources?: FieldSource[]; value_num?: number | null; unit?: string | null; reference_range?: string | null; ref_low?: number | null; ref_high?: number | null; abnormal_flag: AbnormalFlag; reported_abnormal_marker: string | null; abnormal_basis: AbnormalBasis; abnormal_exclusion_reason?: 'HEIGHT_WEIGHT' | 'SECTION_SUMMARY' | null; deviation?: string | null; confidence: number | null; confidence_method: 'calibrated' | 'unavailable'; need_review: boolean; review_issues: ReviewIssue[]; source?: FieldSource }
export interface TaskResult extends ExportEligibility { task_id: string; run_id: string; result_revision: number; doc_type: string; status: TaskStatus; review_issues: ReviewIssue[]; fields?: Field[]; basic_info?: Record<string, Field>; items?: MedicalItem[]; stats?: { total: number | null; normal: number | null; abnormal: number | null; unknown: number | null; categories: string[] }; abnormal_summary?: MedicalItem[]; normal_summary?: string | null; report_summary?: ReportSummary; limitations?: string[]; members?: Record<string, Field>[]; generic?: { full_text: string; key_values: { key: string; value: string | null }[] }; reviewed_generic?: { full_text: string; key_values: { key: string; value: string | null }[] } }
export const runningStatuses = new Set<TaskStatus>(['QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'])
export const hasResult = (task: Pick<Task, 'status'>) => ['NEED_REVIEW', 'COMPLETED', 'FAILED'].includes(task.status)
export const resultKey = (task: Pick<Task, 'task_id' | 'run_id' | 'result_revision'>) => `${task.task_id}:${task.run_id}:${task.result_revision}`
export const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const integer = (v: unknown, minimum = 0) => Number.isInteger(v) && Number(v) >= minimum
const uuid = (v: unknown) => typeof v === 'string' && /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(v)
function requireValue(condition: unknown): asserts condition { if (!condition) throw new Error('INVALID_RESPONSE') }
function exportEligibilityValid(value: Record<string, unknown>): boolean {
  return (value.export_ready === undefined || typeof value.export_ready === 'boolean') &&
    (value.export_blockers === undefined || (Array.isArray(value.export_blockers) && value.export_blockers.every(b =>
      isRecord(b) && typeof b.field === 'string' && /^[a-zA-Z_][a-zA-Z0-9_.\[\]]{0,127}$/.test(b.field) &&
      typeof b.code === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(b.code))))
}

export function parseUser(value: unknown): User {
  requireValue(isRecord(value) && typeof value.user_id === 'string' && typeof value.display_name === 'string' && ['viewer', 'operator', 'admin'].includes(String(value.role)) && Array.isArray(value.permissions) && value.permissions.every(p => typeof p === 'string'))
  requireValue(value.csrf_token === undefined || typeof value.csrf_token === 'string' && /^[0-9a-f]{64}$/.test(value.csrf_token))
  return value as unknown as User
}
export function parseBatches(value: unknown): BatchList {
  requireValue(isRecord(value) && Array.isArray(value.items) && integer(value.total) && integer(value.page, 1) && integer(value.page_size, 1))
  requireValue(value.items.every(b => isRecord(b) && uuid(b.batch_id) && typeof b.status === 'string' && Object.hasOwn(batchLabels, b.status)))
  return value as unknown as BatchList
}
export function parseTask(value: unknown): Task {
  requireValue(isRecord(value) && uuid(value.task_id) && uuid(value.run_id) && integer(value.result_revision) && typeof value.cancel_requested === 'boolean' && typeof value.status === 'string' && Object.hasOwn(taskLabels, value.status) && integer(value.page_count) && Array.isArray(value.pages))
  requireValue(exportEligibilityValid(value))
  requireValue(value.batch_id === undefined || uuid(value.batch_id))
  requireValue(value.actual_source_page_count === undefined || integer(value.actual_source_page_count))
  requireValue(value.content_hash === undefined || typeof value.content_hash === 'string' && /^[0-9a-f]{64}$/.test(value.content_hash))
  requireValue(value.progress === undefined || (integer(value.progress) && Number(value.progress) <= 100))
  requireValue(value.extract_options === undefined || (isRecord(value.extract_options) && (value.extract_options.abnormal_only === undefined || typeof value.extract_options.abnormal_only === 'boolean')))
  const task = { ...value } as unknown as Task
  if (value.error != null) {
    requireValue(isRecord(value.error))
    task.error = { code: safeCode(value.error.code), error_id: safeId(value.error.error_id), stage: safeStage(value.error.stage) }
  }
  return task
}
export function parseTasks(value: unknown): Task[] { requireValue(Array.isArray(value)); return value.map(parseTask) }
export function parseCreated(value: unknown): { batch_id: string; task_ids: string[] } {
  requireValue(isRecord(value) && uuid(value.batch_id) && Array.isArray(value.task_ids) && value.task_ids.every(uuid))
  return value as unknown as { batch_id: string; task_ids: string[] }
}
const issuesValid = (value: unknown) => Array.isArray(value) && value.every(i => isRecord(i) && typeof i.message === 'string' && typeof i.code === 'string')
const confidenceValid = (value: Record<string, unknown>) => (value.confidence === null || (typeof value.confidence === 'number' && value.confidence >= 0 && value.confidence <= 1)) && ['calibrated', 'unavailable'].includes(String(value.confidence_method))
function sourceValid(value: unknown): boolean {
  if (!isRecord(value)) return false
  const box = value.bbox
  return (value.page === undefined || integer(value.page, 1)) && (value.region_id === undefined || uuid(value.region_id)) &&
    (value.extraction_method === undefined || (typeof value.extraction_method === 'string' && ['pdf_text', 'ocr'].includes(value.extraction_method))) &&
    (value.bbox_kind === undefined || (typeof value.bbox_kind === 'string' && ['region', 'block', 'row', 'cell'].includes(value.bbox_kind))) &&
    (value.raw_text === undefined || typeof value.raw_text === 'string') &&
    (box === undefined || (Array.isArray(box) && box.length === 4 && box.every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1) && box[0] < box[2] && box[1] < box[3]))
}
const sourcesValid = (value: unknown) => Array.isArray(value) && value.every(sourceValid)
const optionalString = (value: unknown) => value === undefined || value === null || typeof value === 'string'
const optionalNumber = (value: unknown) => value === undefined || value === null || (typeof value === 'number' && Number.isFinite(value))
const optionalSources = (value: unknown) => value === undefined || sourcesValid(value)
function summaryValid(value: unknown): boolean {
  if (!isRecord(value) || !(value.declared_count === null || (Number.isSafeInteger(value.declared_count) && Number(value.declared_count) >= 0)) ||
      typeof value.scope !== 'string' || !['follow_up_required', 'overall_conclusion', 'unidentified'].includes(value.scope) ||
      typeof value.count_check !== 'string' || !['match', 'mismatch', 'unverified'].includes(value.count_check) || !sourcesValid(value.sources) || !Array.isArray(value.findings)) return false
  if (!value.findings.every(f => isRecord(f) && uuid(f.finding_id) && (f.reported_number === null || typeof f.reported_number === 'string') && typeof f.text === 'string' && sourcesValid(f.sources) && optionalString(f.project_name) && (f.result_item_id == null || uuid(f.result_item_id)) && optionalString(f.risk_grade) && optionalString(f.diagnosis) && optionalString(f.result_raw) && optionalSources(f.result_sources))) return false
  if (new Set(value.findings.map(f => f.finding_id)).size !== value.findings.length) return false
  if (value.count_check !== 'unverified' && value.declared_count === null) return false
  if (value.scope !== 'follow_up_required' && (value.declared_count !== null || value.count_check !== 'unverified')) return false
  // Only the backend can verify complete list evidence; reject contradictory claims here.
  if (value.count_check === 'match' && value.declared_count !== value.findings.length) return false
  return true
}
function fieldValid(value: unknown): boolean { return isRecord(value) && typeof value.key === 'string' && typeof value.label === 'string' && (value.value === null || ['string', 'number', 'boolean'].includes(typeof value.value)) && confidenceValid(value) && typeof value.need_review === 'boolean' && issuesValid(value.review_issues) && (value.source === undefined || sourceValid(value.source)) && optionalSources(value.sources) }
function itemValid(value: unknown): boolean { return isRecord(value) && typeof value.item_id === 'string' && typeof value.name === 'string' && typeof value.result_raw === 'string' && ['NORMAL', 'HIGH', 'LOW', 'ABNORMAL', 'POSITIVE', 'UNKNOWN'].includes(String(value.abnormal_flag)) && ['report_marker', 'report_grade', 'reference_comparison', 'unknown'].includes(String(value.abnormal_basis)) && (value.abnormal_exclusion_reason == null || value.abnormal_exclusion_reason === 'HEIGHT_WEIGHT' || value.abnormal_exclusion_reason === 'SECTION_SUMMARY') && confidenceValid(value) && typeof value.need_review === 'boolean' && issuesValid(value.review_issues) && (value.source === undefined || sourceValid(value.source)) && optionalString(value.reported_abnormal_marker) && optionalString(value.risk_grade) && optionalString(value.diagnosis) && optionalSources(value.diagnosis_sources) && optionalNumber(value.value_num) && optionalNumber(value.ref_low) && optionalNumber(value.ref_high) && optionalString(value.deviation) }
export function parseResult(value: unknown): TaskResult {
  requireValue(isRecord(value) && uuid(value.task_id) && uuid(value.run_id) && integer(value.result_revision) && typeof value.doc_type === 'string' && typeof value.status === 'string' && Object.hasOwn(taskLabels, value.status) && issuesValid(value.review_issues))
  requireValue(exportEligibilityValid(value))
  requireValue(value.fields === undefined || (Array.isArray(value.fields) && value.fields.every(fieldValid)))
  requireValue(value.members === undefined || (Array.isArray(value.members) && value.members.every(member => isRecord(member) && Object.entries(member).every(([key,v]) => key === 'member_id' ? uuid(v) : key === 'source_page' ? integer(v,1) : fieldValid(v)))))
  for (const key of ['generic', 'reviewed_generic']) {
    const generic = value[key]
    requireValue(generic === undefined || (isRecord(generic) && typeof generic.full_text === 'string' && Array.isArray(generic.key_values) && generic.key_values.every(pair => isRecord(pair) && typeof pair.key === 'string' && (pair.value === null || typeof pair.value === 'string'))))
  }
  requireValue(value.basic_info === undefined || (isRecord(value.basic_info) && Object.values(value.basic_info).every(fieldValid)))
  requireValue(value.items === undefined || (Array.isArray(value.items) && value.items.every(itemValid)))
  requireValue(value.abnormal_summary === undefined || (Array.isArray(value.abnormal_summary) && value.abnormal_summary.every(itemValid)))
  requireValue(value.report_summary === undefined || (value.doc_type === 'MEDICAL_REPORT' && summaryValid(value.report_summary)))
  requireValue(value.limitations === undefined || (Array.isArray(value.limitations) && value.limitations.every(v => typeof v === 'string')))
  if (value.doc_type === 'MEDICAL_REPORT') {
    requireValue(isRecord(value.basic_info) && Array.isArray(value.items) && Array.isArray(value.abnormal_summary) && isRecord(value.stats))
    requireValue(['total', 'normal', 'abnormal', 'unknown'].every(k => value.stats && isRecord(value.stats) && (value.stats[k] === null || integer(value.stats[k]))))
    requireValue(Array.isArray(value.stats.categories) && value.stats.categories.every(c => typeof c === 'string'))
  }
  return value as unknown as TaskResult
}

export function validateUpload(files: readonly Pick<File, 'size' | 'name'>[]): string | null {
  if (files.length < 1 || files.length > 20) return '请选择 1–20 个文件。'
  if (files.some(f => !/\.(?:pdf|jpe?g|png|heic)$/i.test(f.name))) return '请选择 JPG、PNG、HEIC 或 PDF 文件。'
  if (files.some(f => f.size <= 0)) return '文件内容为空，请检查后重新选择。'
  if (files.some(f => f.size > 10 * 1024 * 1024)) return '单个文件不能超过 10 MB。'
  if (files.reduce((sum, f) => sum + f.size, 0) > 50 * 1024 * 1024) return '本批次文件总大小不能超过 50 MB。'
  return null
}
export const abnormalBasisLabels: Record<AbnormalBasis, string> = { report_marker: '报告标记', report_grade: '报告等级', reference_comparison: '参考区间比较', unknown: '依据不足' }
export const isMedicalReviewItem = (item: Pick<MedicalItem, 'abnormal_exclusion_reason'>) => !item.abnormal_exclusion_reason
export function matchesMedicalFilter(item: MedicalItem, filter: ItemsFilter): boolean {
  if (filter === 'all') return true
  if (item.abnormal_exclusion_reason) return false
  if (filter === 'unknown') return item.abnormal_flag === 'UNKNOWN' || (item.abnormal_flag === 'POSITIVE' && item.abnormal_basis === 'unknown')
  return ['HIGH', 'LOW', 'ABNORMAL'].includes(item.abnormal_flag) || (item.abnormal_flag === 'POSITIVE' && item.abnormal_basis !== 'unknown')
}
export function parseManagedUser(value: unknown): ManagedUser {
  requireValue(isRecord(value) && Object.keys(value).length === 5 && uuid(value.user_id) &&
    typeof value.username === 'string' && typeof value.display_name === 'string' &&
    ['viewer', 'operator', 'admin'].includes(String(value.role)) && typeof value.enabled === 'boolean')
  return value as unknown as ManagedUser
}
export function parseManagedUsers(value: unknown): ManagedUser[] {
  requireValue(isRecord(value) && Array.isArray(value.items))
  return value.items.map(parseManagedUser)
}
export function medicalFlag(item: MedicalItem): string {
  if (item.abnormal_exclusion_reason === 'HEIGHT_WEIGHT') return '不计异常'
  if (item.abnormal_exclusion_reason === 'SECTION_SUMMARY') return '小结 · 不计项目'
  if (item.abnormal_basis === 'unknown') return item.abnormal_flag === 'POSITIVE' ? '阳性 · 待判定' : '待判定'
  return { NORMAL: '正常', HIGH: '偏高', LOW: '偏低', ABNORMAL: '异常', POSITIVE: '阳性', UNKNOWN: '待判定' }[item.abnormal_flag]
}
export function confidenceText(field: Pick<Field, 'confidence' | 'confidence_method'>): string {
  return field.confidence_method === 'calibrated' && field.confidence !== null ? `${Math.round(field.confidence * 100)}%` : '未标定'
}

// 性别字段（契约值 M/F）按用户要求以中文展示与编辑；提交新值时写回中文。
const genderLabels: Record<string, string> = { M: '男', F: '女', m: '男', f: '女', male: '男', female: '女', 男: '男', 女: '女' }
export const isGenderKey = (key: string) => key === 'gender' || key === 'sex'
export function genderText(value: unknown): string {
  if (typeof value === 'string' && genderLabels[value]) return genderLabels[value]
  return value === null || value === undefined ? '' : String(value)
}
