import { validateUpload } from './business.ts'
import type { MedicalItem, Task } from './business.ts'

export interface LocalPreview { url: string; name: string; kind: 'pdf' | 'image' | 'heic' }

const previewKind = (name: string): LocalPreview['kind'] => (/\.pdf$/i.test(name) ? 'pdf' : /\.heic$/i.test(name) ? 'heic' : 'image')

// Retains local object URLs for the most recent batches of this page session
// so switching document types keeps earlier batches comparable against their
// originals. The server never returns file content; batches beyond the
// rolling cap are revoked, as is everything on logout/unmount.
export class LocalPreviewBatch {
  private entries = new Map<string, LocalPreview>()
  private batches: string[][] = []
  private generation = 0
  private readonly maxBatches: number
  private readonly create: (file: File) => string
  private readonly revoke: (url: string) => void
  constructor(maxBatches = 5, create: (file: File) => string = (file: File) => URL.createObjectURL(file), revoke: (url: string) => void = (url: string) => URL.revokeObjectURL(url)) {
    this.maxBatches = Math.max(1, Math.floor(maxBatches))
    this.create = create
    this.revoke = revoke
  }
  get(taskId: string) { return this.entries.get(taskId) }
  async addMatched(files: readonly File[], tasks: readonly Task[]): Promise<boolean> {
    const generation = this.generation
    const matchedFiles: File[] = [], ids: string[] = []
    for (const file of files) {
      const bytes = await file.arrayBuffer()
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('')
      const matches = tasks.filter(t => t.content_hash === digest)
      if (matches.length !== 1) return false
      if (!ids.includes(matches[0]!.task_id)) { matchedFiles.push(file); ids.push(matches[0]!.task_id) }
    }
    return generation === this.generation && this.add(matchedFiles, ids)
  }
  clear() {
    this.generation++
    for (const entry of this.entries.values()) this.revoke(entry.url)
    this.entries.clear()
    this.batches = []
  }
  remove(taskIds: readonly string[]) {
    this.generation++ // Do not recreate deleted previews from an in-flight hash match.
    const removed = new Set(taskIds)
    for (const id of removed) {
      const entry = this.entries.get(id)
      if (entry) { this.revoke(entry.url); this.entries.delete(id) }
    }
    this.batches = this.batches.map(ids => ids.filter(id => !removed.has(id))).filter(ids => ids.length)
  }
  add(files: readonly File[], taskIds: readonly string[]): boolean {
    if (validateUpload(files) || taskIds.length !== files.length || new Set(taskIds).size !== taskIds.length ||
      taskIds.some(id => !/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(id))) return false
    const created: [string, LocalPreview][] = []
    try {
      files.forEach((file, index) => {
        const id = taskIds[index]!
        if (!this.entries.has(id)) created.push([id, { url: this.create(file), name: file.name, kind: previewKind(file.name) }])
      })
      created.forEach(([id, entry]) => this.entries.set(id, entry))
      this.batches.push(taskIds.slice())
    } catch {
      created.forEach(([, entry]) => this.revoke(entry.url))
      return false
    }
    while (this.batches.length > this.maxBatches) {
      const removed = this.batches.shift()!
      for (const id of removed) {
        const entry = this.entries.get(id)
        if (entry) { this.revoke(entry.url); this.entries.delete(id) }
      }
    }
    return true
  }
}

export function sourcePage(value: unknown, pageCount: number, kind: LocalPreview['kind']): number | null {
  const limit = kind === 'pdf' ? (pageCount > 0 ? pageCount : 100) : 1
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1 && value <= limit ? value : null
}

// Local projection over the currently returned items only. It never claims
// full-report coverage; the server-side items_filter stays the primary view switch.
export function searchMedicalItems(items: readonly MedicalItem[], query: string, reviewOnly: boolean): MedicalItem[] {
  const search = query.trim().toLocaleLowerCase()
  return items.filter(item => {
    const matches = [item.name, item.alias, item.category].some(label => (label ?? '').toLocaleLowerCase().includes(search))
    return matches && (!reviewOnly || item.need_review)
  })
}

export interface PendingOperation { operation: 'cancel' | 'rerun'; task_id: string; run_id: string }
export function pendingOperationText(pending: PendingOperation, tasks: readonly Task[]): string {
  const task = tasks.find(item => item.task_id === pending.task_id && item.run_id === pending.run_id)
  if (!task) return ''
  if (pending.operation === 'rerun') return task.status === 'QUEUED' ? '已接受重跑请求，新执行正在排队。' : ''
  return task.cancel_requested && ['QUEUED', 'PREPROCESSING', 'OCR', 'EXTRACTING', 'VALIDATING'].includes(task.status) ? '已请求取消；等待服务确认停止后才会显示“已取消”。' : ''
}
