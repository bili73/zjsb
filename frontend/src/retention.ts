import { isRecord } from './business.ts'

export type RetentionDays = 7 | 15 | 30 | null
export interface RetentionSettings {
  days: RetentionDays; revision: number; assessed_at: string
  impact: { days: 7 | 15 | 30; eligible_count: number; active_count: number }[]
}
const count = (v: unknown) => Number.isSafeInteger(v) && (v as number) >= 0
export function parseRetentionSettings(value: unknown): RetentionSettings {
  if (!isRecord(value) || !(value.days === null || [7, 15, 30].includes(value.days as number)) || !count(value.revision)
    || typeof value.assessed_at !== 'string' || !Number.isFinite(Date.parse(value.assessed_at))
    || !Array.isArray(value.impact) || value.impact.length !== 3) throw new Error('INVALID_RESPONSE')
  const impact = value.impact
  if (![7, 15, 30].every(days => impact.filter((item: unknown) => isRecord(item) && item.days === days
    && count(item.eligible_count) && count(item.active_count)).length === 1)) throw new Error('INVALID_RESPONSE')
  return value as unknown as RetentionSettings
}
export const retentionLabel = (days: RetentionDays) => days === null ? '永不清除' : `${days}天`
export function retentionWarning(settings: RetentionSettings, days: RetentionDays): string {
  const common = `文件保留将从“${retentionLabel(settings.days)}”改为“${retentionLabel(days)}”，应用于所有账号已上传及今后上传的文件。`
  if (days === null) return common + '停止自动清理原件、识别结果及修改历史，仍可手动删除。已清理的文件不会恢复。确认保存？'
  const impact = settings.impact.find(item => item.days === days)!
  return common + `每份文件从原上传时间起算，不从本次保存重新计时。按读取设置时的统计，${impact.eligible_count} 个文件已超过所选期限，可能在下一次自动清理时删除；另有 ${impact.active_count} 个超期文件正在排队或处理，会延后到处理结束或取消后清理。数量可能随时间和任务变化。到期后将一并删除原件、识别结果及修改历史，已清理数据不能恢复，请先导出需保留的内容。确认保存？`
}
export async function confirmRetentionSave(settings: RetentionSettings, days: RetentionDays,
  confirm: (message: string) => Promise<unknown>, save: (body: { days: RetentionDays; expected_revision: number; confirmed: true }) => Promise<RetentionSettings>,
): Promise<RetentionSettings | null> {
  try { await confirm(retentionWarning(settings, days)) } catch { return null }
  return save({ days, expected_revision: settings.revision, confirmed: true })
}
