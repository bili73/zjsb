import { runningStatuses } from './business.ts'
import type { BatchOwner, Task, TaskStatus } from './business.ts'

export function batchOwnerLabel(owner?: BatchOwner): string {
  if (!owner?.user_id) return '未知上传人'
  if (!owner.username) return '历史账号（未关联）'
  return `${owner.display_name ?? owner.username}（${owner.username}${owner.account_exists ? '' : '，已删除'}）`
}

// Business timestamps stay UTC on the wire; display never follows the host timezone.
const clock = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

export function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  const value = new Date(iso)
  if (!Number.isFinite(value.getTime())) return '—'
  return clock.format(value)
}

export function shanghaiDate(value = new Date()): string {
  return formatTime(value.toISOString()).slice(0, 10).replace(/-/g, '')
}

// 保留期遵循契约默认值：业务文件、结果与运行历史自任务创建起保留 7 天，到期清理。
// 服务端未下发 expires_at 字段，按创建时间 +7 天推算；无法解析时返回空串由调用方省略展示。
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000
export function expiryText(iso?: string | null): string {
  if (!iso) return ''
  const value = new Date(iso)
  if (!Number.isFinite(value.getTime())) return ''
  return formatTime(new Date(value.getTime() + RETENTION_MS).toISOString()).slice(0, 10)
}

const progressLabels: Record<TaskStatus, string> = {
  QUEUED: '排队等待', PREPROCESSING: '准备文件中', OCR: '文字识别中', EXTRACTING: '整理字段中', VALIDATING: '校验结果中',
  NEED_REVIEW: '识别结束，待核对', COMPLETED: '已完成', FAILED: '处理失败', REJECTED: '已拒绝', CANCELLED: '已取消',
}

export function taskProgressView(task: Pick<Task, 'status' | 'progress_detail'>) {
  const detail = task.progress_detail
  const active = task.status !== 'QUEUED' && runningStatuses.has(task.status)
  // This measures OCR units only, never the completion time of the entire task.
  const percentage = task.status === 'OCR' && detail?.total_regions != null && detail.total_regions > 0
    ? Math.floor(detail.processed_regions * 100 / detail.total_regions) : null
  const pages = detail ? `已准备 ${detail.prepared_pages}${detail.total_pages === null ? '' : `/${detail.total_pages}`} 页` : ''
  let amount = ''
  if (detail && task.status !== 'QUEUED') {
    if (task.status === 'PREPROCESSING') amount = pages
    else if (detail.total_regions === 0) amount = '无需图像识别'
    else amount = `已处理 ${detail.processed_regions}${detail.total_regions === null ? ' 个区域（总数未知）' : `/${detail.total_regions} 个区域`}`
  }
  const tooltip = detail
    ? `${pages}；已识别 ${detail.recognized_regions} 个区域；${detail.incomplete_regions} 个不完整。区域是文字或表格片段；处理量不代表准确率、剩余时间或人工核对通过。`
    : ''
  return { label: progressLabels[task.status], active, percentage, amount, tooltip, incomplete: detail?.incomplete_regions ?? 0 }
}
