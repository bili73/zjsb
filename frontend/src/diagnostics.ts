import { ref } from 'vue'

export const errorMessages = {
  EXPORT_BLOCKED: '选择中有任务的必填字段未填写完整，整份导出已阻止；请补齐并保存。', PREVIEW_MASK_UNAVAILABLE: '当前服务的预览合同已变化，请刷新或确认服务版本。', BANK_CROP_REQUIRED: '请裁选完整卡号一行，去除其他内容。', BANK_UNSAFE_CONTENT: '卡号区域含其他内容，请重新紧裁剪。',
  UNSAFE_CARD_INPUT: '请仅裁选完整卡号一行，去除姓名、有效期和安全码。', CARD_ADMISSION_FAILED: '卡号区域未可靠读出，请等待引擎就绪或重新裁紧卡号后再试。',
  INVALID_REQUEST: '请求内容不符合要求。', FILE_TOO_LARGE: '文件、图片像素或批次超过限制：单文件 10 MB，图片 4000 万像素，每批 20 个文件、共 50 MB。',
  UNSUPPORTED_FORMAT: '暂不支持此图片编码或多帧材料；请另存为单张 JPG/PNG，或将多页转换为 PDF。', IMAGE_UNREADABLE: '图片无法读取，请换用清晰文件。',
  DECODE_FAILED: '文件无法解码，请重新导出图片或使用未加密的 PDF。', NO_DOC_EDGE: '未能确定材料边界。', LOW_QUALITY: '材料清晰度不足。',
  OVEREXPOSED: '材料曝光过度。', UNSUPPORTED_DOC_TYPE: '暂不支持该材料类型。',
  LUHN_FAILED: '号码校验未通过。', MULTI_CANDIDATES: '识别得到多个候选，需人工核对。',
  ID_CHECKSUM_FAILED: '身份证校验未通过。', USCC_CHECKSUM_FAILED: '统一社会信用代码校验未通过。',
  XUEXIN_CODE_INVALID: '验证码格式需核对。', MISSING_REQUIRED_FIELD: '缺少必填信息。',
  EXTRACT_TIMEOUT: '识别超时，请检查任务状态后决定是否重跑。', WORKER_INTERRUPTED: '处理进程中断。',
  SETTINGS_VERSION_CONFLICT: '必填设置已被其他管理员修改；当前选择已保留，请重新读取后再保存。',
  RESULT_VERSION_CONFLICT: '任务版本已变化；草稿已保留，请明确刷新并重新核对。',
  OCR_TOKEN_LIMIT: '模型输出达到长度上限，结果可能不完整。', OCR_REPETITION: '模型输出出现重复，结果需核对。',
  MODEL_CONFLICT: '模型结果存在冲突。', BIN_UNKNOWN: '本地号码规则未覆盖该号码。',
  TASK_NOT_REVIEWABLE: '任务当前不能复核。', FORBIDDEN_REVEAL: '没有查看完整敏感值的权限。',
  INVALID_STATE: '任务状态已变化，当前操作不可执行。', INTERNAL_ERROR: '服务处理失败，请保留错误编号。',
  UNAUTHORIZED: '账号或密码错误，或登录已失效，请重新登录。', FORBIDDEN: '登录校验或权限无效，请刷新工作台后重试。',
  LOGIN_THROTTLED: '登录尝试过多，请五分钟后再试。', AUTH_NOT_CONFIGURED: '账号尚未配置，请联系管理员。',
  USERNAME_EXISTS: '账号已存在，请使用其他账号名；原账号不会被修改。',
  ACCOUNT_PROTECTED: '当前账号或最后一个启用的管理员受保护，不能执行该操作；自己的密码请从右上角修改。',
  CURRENT_PASSWORD_INCORRECT: '原密码不正确，请重新输入。',
  NOT_FOUND: '请求的记录暂不存在。', NETWORK_ERROR: '无法连接本地服务，请确认启动器仍在运行。',
  REQUEST_TIMEOUT: '服务未在等待时间内响应。', INVALID_RESPONSE: '服务响应格式不符合约定。',
  CLIENT_ERROR: '界面发生错误，请复制诊断信息交给维护人员。', UNKNOWN_ERROR: '操作未完成，请查看错误编号。',
} as const
export type ErrorCode = keyof typeof errorMessages
export type Operation = 'health' | 'auth' | 'account_list' | 'account_create' | 'account_update' | 'account_delete' | 'password_change' | 'required_settings_read' | 'required_settings_save' | 'batch_list' | 'batch_tasks' | 'batch_delete' | 'upload' | 'result' | 'cancel' | 'rerun' | 'interface' | 'catalogue' | 'review' | 'preview' | 'export'
export type Stage = 'BOOTSTRAP' | 'QUEUED' | 'PREPROCESSING' | 'OCR' | 'EXTRACTING' | 'VALIDATING' | 'PUBLISHING' | 'CLEANUP'
export type DiagnosticOrigin = 'http' | 'task' | 'vue' | 'window' | 'promise'
const stages = new Set(['BOOTSTRAP', 'QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING', 'PUBLISHING', 'CLEANUP'])
const origins = new Set(['http', 'task', 'vue', 'window', 'promise'])
const operations = new Set(['health', 'auth', 'account_list', 'account_create', 'account_update', 'account_delete', 'password_change', 'required_settings_read', 'required_settings_save', 'batch_list', 'batch_tasks', 'batch_delete', 'upload', 'result', 'cancel', 'rerun', 'interface', 'catalogue', 'review', 'preview', 'export'])
const exceptionNames = new Set(['Error', 'TypeError', 'RangeError', 'SyntaxError', 'ReferenceError', 'URIError', 'EvalError', 'DOMException'])
export function safeId(value: unknown): string | null {
  return typeof value === 'string' && (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) || /^e_[A-Za-z0-9]{1,80}$/.test(value)) ? value : null
}
export function safeCode(value: unknown): ErrorCode {
  return typeof value === 'string' && Object.hasOwn(errorMessages, value) ? value as ErrorCode : 'UNKNOWN_ERROR'
}
export function safeStage(value: unknown): Stage | null { return typeof value === 'string' && stages.has(value) ? value as Stage : null }

export interface DiagnosticCard {
  schema_version: 1
  error_id: string
  request_id: string | null
  occurred_at: string
  app_version: string
  origin: DiagnosticOrigin
  operation: Operation
  code: ErrorCode
  http_status: number | null
  stage: Stage | null
  exception_type: string | null
  stack_frames: { module: 'frontend'; line: number; column: number }[]
}
export const diagnosticCards = ref<DiagnosticCard[]>([])
let appVersion = 'unknown'
export function setDiagnosticVersion(value: string) { appVersion = /^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/.test(value) ? value : 'unknown' }

// Never retain message, filename, URL, body, headers, key or document values.
export function makeDiagnostic(input: {
  origin: DiagnosticOrigin; operation: Operation; code?: unknown; error_id?: unknown;
  request_id?: unknown; status?: number; stage?: unknown; error?: unknown
}): DiagnosticCard {
  const error = input.error instanceof Error ? input.error : null
  const frames: DiagnosticCard['stack_frames'] = []
  if (error && typeof error.stack === 'string') {
    for (const line of error.stack.split('\n').slice(1, 9)) {
      const match = /:(\d{1,7}):(\d{1,7})\)?\s*$/.exec(line)
      if (match) frames.push({ module: 'frontend', line: Number(match[1]), column: Number(match[2]) })
    }
  }
  return {
    schema_version: 1, error_id: safeId(input.error_id) ?? safeId(input.request_id) ?? crypto.randomUUID(),
    request_id: safeId(input.request_id), occurred_at: new Date().toISOString(), app_version: appVersion,
    origin: origins.has(input.origin) ? input.origin : 'window',
    operation: operations.has(input.operation) ? input.operation : 'interface', code: safeCode(input.code),
    http_status: Number.isInteger(input.status) && input.status! >= 100 && input.status! <= 599 ? input.status! : null,
    stage: safeStage(input.stage), exception_type: error && exceptionNames.has(error.name) ? error.name : null, stack_frames: frames,
  }
}
export function recordDiagnostic(input: Parameters<typeof makeDiagnostic>[0]): DiagnosticCard {
  const card = makeDiagnostic(input)
  const existing = diagnosticCards.value.find(item => item.error_id === card.error_id)
  if (existing) return existing
  diagnosticCards.value = [card, ...diagnosticCards.value].slice(0, 20)
  return card
}
export function installGlobalDiagnostics() {
  const onError = (event: ErrorEvent) => { recordDiagnostic({ origin: 'window', operation: 'interface', code: 'CLIENT_ERROR', error: event.error }) }
  const onRejection = (event: PromiseRejectionEvent) => { recordDiagnostic({ origin: 'promise', operation: 'interface', code: 'CLIENT_ERROR', error: event.reason }) }
  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)
  return () => { window.removeEventListener('error', onError); window.removeEventListener('unhandledrejection', onRejection) }
}
