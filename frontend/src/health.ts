export type ModelState = 'unloaded' | 'loading' | 'warming' | 'ready' | 'failed' | 'stopping'
export type ResidencyMode = 'dual_resident' | 'single_resident'
export type RuntimeState = 'starting' | 'ready' | 'degraded' | 'stopping'
export type ReasonCode = 'RESOURCE_LIMIT' | 'MODEL_LOAD_FAILED' | 'MODEL_WARMUP_FAILED' | 'MODEL_PROCESS_EXITED' | 'SUPERVISION_FAILED'

export interface RuntimeHealth {
  configured_mode: ResidencyMode
  effective_mode: ResidencyMode | 'ocr_unavailable' | null
  state: RuntimeState
  models: { glm_ocr: ModelState; paddleocr_vl: ModelState }
  reason_code: ReasonCode | null
}

export interface Health {
  status: 'ok' | 'degraded'
  version: string
  queue_depth: number | null
  components: { db: 'ok' | 'down'; worker: 'ok' | 'down'; storage: 'ok' | 'down' }
  runtime?: RuntimeHealth
}

const modelStates = ['unloaded', 'loading', 'warming', 'ready', 'failed', 'stopping']
const modes = ['dual_resident', 'single_resident']
const runtimeStates = ['starting', 'ready', 'degraded', 'stopping']
const reasons = ['RESOURCE_LIMIT', 'MODEL_LOAD_FAILED', 'MODEL_WARMUP_FAILED', 'MODEL_PROCESS_EXITED', 'SUPERVISION_FAILED']
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const member = (value: unknown, values: readonly string[]) => typeof value === 'string' && values.includes(value)

// Reject malformed snapshots rather than inventing model readiness.
export function parseHealth(value: unknown): Health {
  if (!record(value) || !member(value.status, ['ok', 'degraded']) || typeof value.version !== 'string'
    || !(value.queue_depth === null || (Number.isInteger(value.queue_depth) && Number(value.queue_depth) >= 0))
    || !record(value.components) || !['db', 'worker', 'storage'].every(key => member((value.components as Record<string, unknown>)[key], ['ok', 'down']))) {
    throw new Error('INVALID_HEALTH')
  }
  if (value.runtime !== undefined) {
    const runtime = value.runtime
    if (!record(runtime) || !member(runtime.configured_mode, modes)
      || !(runtime.effective_mode === null || member(runtime.effective_mode, [...modes, 'ocr_unavailable']))
      || !member(runtime.state, runtimeStates) || !record(runtime.models)
      || !member(runtime.models.glm_ocr, modelStates) || !member(runtime.models.paddleocr_vl, modelStates)
      || !(runtime.reason_code === null || member(runtime.reason_code, reasons))) {
      throw new Error('INVALID_HEALTH')
    }
  }
  return value as unknown as Health
}

export function needsStartupRefresh(health: Health): boolean {
  const runtime = health.runtime
  return !!runtime && (runtime.state === 'starting' || runtime.state === 'stopping'
    || Object.values(runtime.models).some(state => ['loading', 'warming', 'stopping'].includes(state)))
}

export const modelLabels: Record<ModelState, string> = {
  unloaded: '未加载', loading: '加载中', warming: '预热中', ready: '已就绪', failed: '不可用', stopping: '正在停止',
}
export const modelDescriptions: Record<ModelState, string> = {
  unloaded: '当前未驻留。单模型模式下，这可以是正常状态。',
  loading: '正在加载模型，请等待服务返回下一阶段。',
  warming: '正在进行预热，完成后才能接受识别调度。',
  ready: '已加载并完成预热，可接受服务调度。',
  failed: '该模型当前不可用，请查看下方原因说明。',
  stopping: '正在释放模型资源，请等待程序退出。',
}
export const modeLabels = { dual_resident: '双模型驻留', single_resident: '单模型驻留', ocr_unavailable: 'OCR 不可用' }
export const reasonDescriptions: Record<ReasonCode, string> = {
  RESOURCE_LIMIT: '可用资源不足。请以当前运行模式和各模型状态为准；自动降级不会改写保存的配置。',
  MODEL_LOAD_FAILED: '模型加载失败，可能涉及模型文件、依赖或兼容性。此次会话不会因刷新页面而重试加载。',
  MODEL_WARMUP_FAILED: '模型预热未成功，尚不能用于识别。刷新仅查询状态，不会重新启动模型。',
  MODEL_PROCESS_EXITED: '模型进程已经退出，对应模型当前不可用。',
  SUPERVISION_FAILED: '进程监督未能正常工作。请关闭启动器后重新启动程序。',
}
