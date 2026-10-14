import { safeCode, safeId, safeStage } from './diagnostics.ts'
import type { ErrorCode, Stage } from './diagnostics.ts'
import type { PhotoTable, TableDraft } from './table-review.ts'
import { validTableResponse } from './table-review.ts'
import type { GenericDraft, GenericResult } from './generic-review.ts'

export const docTypes = {
  TABLE: '表格', MEDICAL_REPORT: '体检报告', DIPLOMA: '毕业证', DEGREE_CERT: '学位证',
  BANK_CARD: '银行卡', ID_CARD_FRONT: '身份证人像面', ID_CARD_BACK: '身份证国徽面', PASSPORT: '护照',
  HOUSEHOLD_REGISTER: '户口本', BUSINESS_LICENSE: '营业执照', GENERIC: '通用识别', XUEXIN_DIPLOMA_TABLE: '学历证书电子注册备案表',
} as const
export type UploadDocType = keyof typeof docTypes
export interface Classification { doc_type: UploadDocType | null; basis: 'content' | 'filename' | 'unknown'; reason: string; candidates: UploadDocType[] }
export function parseClassification(value: unknown): Classification {
  requireValue(isRecord(value) && (value.doc_type === null || typeof value.doc_type === 'string' && Object.hasOwn(docTypes, value.doc_type)) &&
    ['content', 'filename', 'unknown'].includes(String(value.basis)) && typeof value.reason === 'string' && value.reason.length <= 200 &&
    Array.isArray(value.candidates) && value.candidates.every(type => typeof type === 'string' && Object.hasOwn(docTypes, type)))
  requireValue(value.basis === 'unknown' ? value.doc_type === null : value.doc_type !== null && value.candidates.includes(value.doc_type))
  return value as unknown as Classification
}
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
export interface BatchOwner { user_id: string | null; username: string | null; display_name: string | null; account_exists: boolean }
export type IdCardPairing = 'unassigned' | 'not_provided' | 'missing_front' | 'missing_back' | 'both_present'
export interface PersonNameSuggestion { name: string; sources: { task_id: string; doc_type: UploadDocType; file_name: string }[] }
export interface Batch { batch_id: string; display_name?: string; status: BatchStatus; file_count?: number; completed_count?: number; need_review_count?: number; failed_count?: number; created_at?: string; updated_at?: string; expires_at?: string | null; required_fields_revision?: number; owner?: BatchOwner; package_revision?: number; person_name?: string | null; is_person_package?: boolean; name_suggestions?: PersonNameSuggestion[]; id_card_pairing?: IdCardPairing; warnings?: { code: string; message: string }[] }
export const isPersonPackage = (batch: Batch) => batch.is_person_package === true || !!batch.person_name
export const pairingLabels: Record<IdCardPairing, string> = { unassigned: '未指定人员', not_provided: '尚未上传身份证', missing_front: '缺少身份证人像面', missing_back: '国徽面未上传（可选，可仅识别人像面）', both_present: '身份证两面已上传，仍需核对是否属于同一人' }
export function sampleQualification(kind: UploadDocType): string {
  if (kind === 'TABLE') return '上传JPG/PNG/HEIC表格照片，自动摆正并识别主体；请核对标题、表头、划除行及表外手写补录。每张独立导出，暂不接收PDF或自动拼接续表。'
  return ['DIPLOMA', 'DEGREE_CERT', 'BANK_CARD', 'XUEXIN_DIPLOMA_TABLE', 'MEDICAL_REPORT'].includes(kind)
    ? '已有有限真实样本测试，尚不代表所有版式准确率；请对照原件核对。'
    : '规则已接入，尚缺真实样本验收；请逐项对照原件核对。'
}
export interface BatchList { items: Batch[]; total: number; page: number; page_size: number }
export interface TaskError { code: ErrorCode; error_id: string | null; stage: Stage | null }
export interface ExportEligibility { export_ready?: boolean; export_blockers?: { field: string; code: string }[]; required_fields_revision?: number; required_field_keys?: string[] }
export interface Task extends ExportEligibility { task_id: string; batch_id?: string; run_id: string; result_revision: number; cancel_requested: boolean; status: TaskStatus; file_name?: string; doc_type?: string; progress?: number; page_count: number; actual_source_page_count?: number | null; content_hash?: string; expires_at?: string; pages: { page_id: string; page_index: number; extraction_method: string; regions?: { region_id: string }[] }[]; error?: TaskError | null; extract_options?: { abnormal_only?: boolean }; progress_detail?: ProgressDetail }
// 进度明细：以已完成的物理 OCR 区域为计量单位。total_* 在区域计划未知（准备中/历史任务）时为 null，
// 不提供估计分母；processed_regions 表示重试策略结束后到达终态的区域数，不保证识别正确。
export interface ProgressDetail { stage: TaskStatus; prepared_pages: number; total_pages: number | null; processed_regions: number; recognized_regions: number; incomplete_regions: number; total_regions: number | null }
export type ItemsFilter = 'all' | 'abnormal' | 'unknown'
export interface ReviewIssue { issue_id: string; code: string; message: string; can_accept: boolean }
export interface FieldSource { page?: number; region_id?: string; extraction_method?: 'pdf_text' | 'ocr'; bbox?: [number, number, number, number]; bbox_kind?: 'region' | 'block' | 'row' | 'cell'; raw_text?: string }
export interface ReportFinding { finding_id: string; reported_number: string | null; text: string; sources: FieldSource[]; project_name?: string | null; result_item_id?: string | null; risk_grade?: string | null; diagnosis?: string | null; result_raw?: string | null; result_sources?: FieldSource[]; need_review?: boolean; review_issues?: ReviewIssue[] }
export interface ReportSummary { scope: 'follow_up_required' | 'overall_conclusion' | 'unidentified'; declared_count: number | null; findings: ReportFinding[]; count_check: 'match' | 'mismatch' | 'unverified'; sources: FieldSource[] }
export interface Field { key: string; label: string; value: string | number | boolean | null; value_masked?: string | null; confidence: number | null; confidence_method: 'calibrated' | 'unavailable'; need_review: boolean; review_issues: ReviewIssue[]; source?: FieldSource; sources?: FieldSource[]; candidates?: { value: string | number | boolean | null; reason?: string; source?: FieldSource }[]; required?: boolean; editable?: boolean; absence_reason?: string }
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
export interface TaskResult extends ExportEligibility { tables?: PhotoTable[]; reviewed_tables?: TableDraft[]; task_id: string; run_id: string; result_revision: number; doc_type: string; status: TaskStatus; review_issues: ReviewIssue[]; fields?: Field[]; basic_info?: Record<string, Field>; items?: MedicalItem[]; stats?: { total: number | null; normal: number | null; abnormal: number | null; unknown: number | null; categories: string[] }; abnormal_summary?: MedicalItem[]; normal_summary?: string | null; report_summary?: ReportSummary; limitations?: string[]; members?: Record<string, Field>[]; generic?: GenericResult; reviewed_generic?: GenericDraft }
export const runningStatuses = new Set<TaskStatus>(['QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'])
export const hasResult = (task: Pick<Task, 'status'>) => ['NEED_REVIEW', 'COMPLETED', 'FAILED'].includes(task.status)
export const householdMemberLabels: Record<string, string> = { name: '姓名', gender: '性别', birth_date: '出生日期', ethnicity: '民族', birth_place: '出生地', native_place: '籍贯', id_number: '公民身份号码', relation_to_householder: '与户主关系', education: '文化程度', marital_status: '婚姻状况', occupation: '职业', workplace: '服务处所', migration_address: '迁入地址' }
type RequiredTask = Pick<Task, 'status' | 'doc_type' | 'export_ready' | 'export_blockers'>
export function hasMissingRequiredFields(task: RequiredTask): boolean {
  return hasResult(task) && task.export_ready === false &&
    !task.export_blockers?.some(blocker => ['task', 'doc_type'].includes(blocker.field))
}
export function requiredFieldLabels(task: RequiredTask, catalogue: readonly DocProfile[]): string[] {
  if (!hasMissingRequiredFields(task)) return []
  const labels = new Map(catalogue.find(profile => profile.doc_type === task.doc_type)?.fields.map(field => [field.key, field.label]))
  if (task.doc_type === 'TABLE') return [...new Set((task.export_blockers ?? []).map(blocker => {
    if (blocker.code === 'INCOMPLETE_OUTPUT') return '识别不完整，需补正或确认'
    if (blocker.code === 'INVALID_TABLE') return '表格结构需修正'
    if (blocker.field === 'tables[0].title') return '表格标题缺失或不确定'
    if (blocker.field === 'tables[0].header_rows') return '表头行数不确定'
    return '未获得可导出的表格'
  }))]
  const keys = [...new Set((task.export_blockers ?? []).filter(blocker => blocker.code === 'MISSING').map(blocker => blocker.field))]
  return keys.map(key => {
    if (key === 'generic.full_text') return '正文'
    const member = /^members\[(\d+)\]\.([a-zA-Z_][a-zA-Z0-9_]*)$/.exec(key)
    if (member) return `成员 ${Number(member[1]) + 1} / ${householdMemberLabels[member[2]!] ?? labels.get(member[2]!) ?? member[2]}`
    return labels.get(key) ?? key
  })
}
export const resultKey = (task: Pick<Task, 'task_id' | 'run_id' | 'result_revision' | 'required_fields_revision'>) => `${task.task_id}:${task.run_id}:${task.result_revision}${task.required_fields_revision === undefined ? '' : `:required-${task.required_fields_revision}`}`
export const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const integer = (v: unknown, minimum = 0) => Number.isInteger(v) && Number(v) >= minimum
const uuid = (v: unknown) => typeof v === 'string' && /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(v)
function requireValue(condition: unknown): asserts condition { if (!condition) throw new Error('INVALID_RESPONSE') }
function exportEligibilityValid(value: Record<string, unknown>): boolean {
  return (value.required_fields_revision === undefined || integer(value.required_fields_revision)) &&
    (value.required_field_keys === undefined || Array.isArray(value.required_field_keys) && value.required_field_keys.every(key => typeof key === 'string')) &&
    (value.export_ready === undefined || typeof value.export_ready === 'boolean') &&
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
  requireValue(value.items.every(b => isRecord(b) && uuid(b.batch_id) && typeof b.status === 'string' && Object.hasOwn(batchLabels, b.status) && (b.required_fields_revision === undefined || integer(b.required_fields_revision))))
  requireValue(value.items.every(b => isRecord(b) &&
    (b.person_name === undefined || b.person_name === null || typeof b.person_name === 'string' && b.person_name.trim().length > 0 && b.person_name.length <= 80) &&
    (b.package_revision === undefined || integer(b.package_revision)) &&
    (b.is_person_package === undefined || typeof b.is_person_package === 'boolean') &&
    (b.name_suggestions === undefined || Array.isArray(b.name_suggestions) && b.name_suggestions.every(s =>
      isRecord(s) && typeof s.name === 'string' && s.name.trim().length > 0 && s.name.length <= 80 &&
      Array.isArray(s.sources) && s.sources.length > 0 && s.sources.every(source => isRecord(source) && uuid(source.task_id) &&
        typeof source.doc_type === 'string' && Object.hasOwn(docTypes, source.doc_type) && typeof source.file_name === 'string'))) &&
    (b.expires_at == null || typeof b.expires_at === 'string' && Number.isFinite(Date.parse(b.expires_at))) &&
    (b.id_card_pairing === undefined || typeof b.id_card_pairing === 'string' && Object.hasOwn(pairingLabels, b.id_card_pairing)) &&
    (b.warnings === undefined || Array.isArray(b.warnings) && b.warnings.every(w => isRecord(w) && typeof w.code === 'string' && typeof w.message === 'string')) &&
    (b.is_person_package !== false || !b.person_name) &&
    (typeof b.person_name !== 'string' && b.is_person_package !== true || integer(b.package_revision) && b.id_card_pairing !== undefined && b.id_card_pairing !== 'unassigned') &&
    (b.id_card_pairing === undefined || b.id_card_pairing === 'unassigned' || typeof b.person_name === 'string' || b.is_person_package === true)))
  requireValue(value.items.every(b => {
    const owner = (b as Record<string, unknown>).owner
    return owner === undefined || isRecord(owner) &&
      (owner.user_id === null || typeof owner.user_id === 'string' && owner.user_id.length > 0) &&
      (owner.username === null || typeof owner.username === 'string' && /^[a-z0-9_.-]{1,64}$/.test(owner.username)) &&
      (owner.display_name === null || typeof owner.display_name === 'string' && owner.display_name.trim().length > 0 && owner.display_name.length <= 80) &&
      typeof owner.account_exists === 'boolean' &&
      (!owner.account_exists || owner.user_id !== null && owner.username !== null && owner.display_name !== null)
  }))
  return value as unknown as BatchList
}
const progressDetailValid = (value: unknown, status: unknown): boolean => {
  if (!isRecord(value)) return false
  return value.stage === status && integer(value.prepared_pages) &&
    (value.total_pages === null || integer(value.total_pages, 1)) && integer(value.processed_regions) &&
    integer(value.recognized_regions) && integer(value.incomplete_regions) &&
    (value.total_regions === null || integer(value.total_regions)) &&
    Number(value.processed_regions) === Number(value.recognized_regions) + Number(value.incomplete_regions) &&
    (value.total_pages === null || Number(value.prepared_pages) <= Number(value.total_pages)) &&
    (value.total_regions === null || Number(value.processed_regions) <= Number(value.total_regions))
}
export function parseTask(value: unknown): Task {
  requireValue(isRecord(value) && uuid(value.task_id) && uuid(value.run_id) && integer(value.result_revision) && typeof value.cancel_requested === 'boolean' && typeof value.status === 'string' && Object.hasOwn(taskLabels, value.status) && integer(value.page_count) && Array.isArray(value.pages))
  requireValue(exportEligibilityValid(value))
  requireValue(value.batch_id === undefined || uuid(value.batch_id))
  requireValue(value.expires_at === undefined || typeof value.expires_at === 'string' && Number.isFinite(Date.parse(value.expires_at)))
  requireValue(value.actual_source_page_count == null || integer(value.actual_source_page_count, 1))
  requireValue(value.content_hash === undefined || typeof value.content_hash === 'string' && /^[0-9a-f]{64}$/.test(value.content_hash))
  requireValue(value.progress === undefined || (integer(value.progress) && Number(value.progress) <= 100))
  requireValue(value.progress_detail === undefined || progressDetailValid(value.progress_detail, value.status))
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
function fieldValid(value: unknown): boolean { return isRecord(value) && typeof value.key === 'string' && typeof value.label === 'string' && (value.value === null || ['string', 'number', 'boolean'].includes(typeof value.value)) && confidenceValid(value) && typeof value.need_review === 'boolean' && issuesValid(value.review_issues) && (value.source === undefined || sourceValid(value.source)) && optionalSources(value.sources) && (value.candidates === undefined || Array.isArray(value.candidates) && value.candidates.every(c => isRecord(c) && (c.value === null || ['string','number','boolean'].includes(typeof c.value)) && optionalString(c.reason) && (c.source === undefined || sourceValid(c.source)))) }
function itemValid(value: unknown): boolean { return isRecord(value) && typeof value.item_id === 'string' && typeof value.name === 'string' && typeof value.result_raw === 'string' && ['NORMAL', 'HIGH', 'LOW', 'ABNORMAL', 'POSITIVE', 'UNKNOWN'].includes(String(value.abnormal_flag)) && ['report_marker', 'report_grade', 'reference_comparison', 'unknown'].includes(String(value.abnormal_basis)) && (value.abnormal_exclusion_reason == null || value.abnormal_exclusion_reason === 'HEIGHT_WEIGHT' || value.abnormal_exclusion_reason === 'SECTION_SUMMARY') && confidenceValid(value) && typeof value.need_review === 'boolean' && issuesValid(value.review_issues) && (value.source === undefined || sourceValid(value.source)) && optionalString(value.reported_abnormal_marker) && optionalString(value.risk_grade) && optionalString(value.diagnosis) && optionalSources(value.diagnosis_sources) && optionalNumber(value.value_num) && optionalNumber(value.ref_low) && optionalNumber(value.ref_high) && optionalString(value.deviation) }
export function parseResult(value: unknown): TaskResult {
  if (isRecord(value) && value.doc_type === 'TABLE') requireValue(validTableResponse(value))
  requireValue(isRecord(value) && uuid(value.task_id) && uuid(value.run_id) && integer(value.result_revision) && typeof value.doc_type === 'string' && typeof value.status === 'string' && Object.hasOwn(taskLabels, value.status) && issuesValid(value.review_issues))
  requireValue(exportEligibilityValid(value))
  requireValue(value.fields === undefined || (Array.isArray(value.fields) && value.fields.every(fieldValid)))
  requireValue(value.members === undefined || (Array.isArray(value.members) && value.members.every(member => isRecord(member) && Object.entries(member).every(([key,v]) => key === 'member_id' ? uuid(v) : key === 'source_page' ? integer(v,1) : fieldValid(v)))))
  for (const key of ['generic', 'reviewed_generic']) {
    const generic = value[key]
    requireValue(generic === undefined || (isRecord(generic) && typeof generic.full_text === 'string' && Array.isArray(generic.key_values) && generic.key_values.every(pair => isRecord(pair) && typeof pair.key === 'string' && (pair.value === null || typeof pair.value === 'string'))))
    if (isRecord(generic)) {
      const pairs=generic.key_values as Record<string,unknown>[]
      requireValue(pairs.every(pair=>(pair.pair_id===undefined || uuid(pair.pair_id)) &&
        (pair.source_pair_id===undefined || uuid(pair.source_pair_id)) &&
        (pair.source===undefined || sourceValid(pair.source))))
      requireValue(generic.blocks===undefined || Array.isArray(generic.blocks) && generic.blocks.every(block=>isRecord(block) &&
        typeof block.text==='string' && integer(block.page,1) && optionalString(block.raw_text) && (block.source===undefined || sourceValid(block.source))))
      requireValue(generic.tables===undefined || Array.isArray(generic.tables) && generic.tables.every(table=>isRecord(table) &&
        sourceValid(table.source) && Array.isArray(table.rows) && table.rows.length>0 && table.rows.length<=1000 &&
        table.rows.every(row=>Array.isArray(row) && row.length>0 && row.length<=200 && row.every(cell=>typeof cell==='string')) && Array.isArray(table.merges)))
    }
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

export const uploadLimits = { maxFiles: 100, maxFileMB: 50, maxBatchMB: 500 } as const

export function validateUpload(files: readonly Pick<File, 'size' | 'name'>[]): string | null {
  if (files.length < 1 || files.length > uploadLimits.maxFiles) return `请选择 1–${uploadLimits.maxFiles} 个文件。`
  if (files.some(f => !/\.(?:pdf|jpe?g|png|heic)$/i.test(f.name))) return '请选择 JPG、PNG、HEIC 或 PDF 文件。'
  if (files.some(f => f.size <= 0)) return '文件内容为空，请检查后重新选择。'
  if (files.some(f => f.size > uploadLimits.maxFileMB * 1024 * 1024)) return `单个文件不能超过 ${uploadLimits.maxFileMB} MB。`
  if (files.reduce((sum, f) => sum + f.size, 0) > uploadLimits.maxBatchMB * 1024 * 1024) return `本批次文件总大小不能超过 ${uploadLimits.maxBatchMB} MB。`
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
