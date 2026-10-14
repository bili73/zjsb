// Ordered account preferences; no shared browser storage or legacy-key import.
// 没有自定义记录时展示全部类型；自定义后，后续新增类型默认收纳，避免工作台越来越挤。

export const WORKBENCH_MAX_ENTRIES = 12
export interface WorkbenchLayout { layout: string[] | null; revision: number }
export interface WorkbenchPreferences extends WorkbenchLayout { defaults: WorkbenchLayout }

export function parseWorkbenchPreferences(value: unknown): WorkbenchPreferences {
  const v = value as Partial<WorkbenchPreferences> | null
  if (!v || typeof v !== 'object' || Object.keys(v).length !== 3) throw new Error('INVALID_RESPONSE')
  return { ...parseWorkbenchLayout({ layout: v.layout, revision: v.revision }), defaults: parseWorkbenchLayout(v.defaults) }
}

export function parseWorkbenchLayout(value: unknown): WorkbenchLayout {
  const v = value as Partial<WorkbenchLayout> | null
  if (!v || typeof v !== 'object' || Object.keys(v).length !== 2 ||
      !Number.isSafeInteger(v.revision) || v.revision! < 0 ||
      !(v.layout === null || Array.isArray(v.layout) && v.layout.length <= WORKBENCH_MAX_ENTRIES &&
        v.layout.every(key => typeof key === 'string' && /^[A-Z_]{1,64}$/.test(key)) && new Set(v.layout).size === v.layout.length)) {
    throw new Error('INVALID_RESPONSE')
  }
  return { layout: v.layout === null ? null : [...v.layout!], revision: v.revision! }
}

// layout 为 null 表示从未自定义：全部类型按目录顺序展示。
// 自定义里的未知键（已下线类型）被忽略，重复键去重，超出上限的尾部键收纳。
export function splitEntries(catalogueKeys: readonly string[], layout: readonly string[] | null): { visible: string[]; hidden: string[] } {
  if (!layout) return { visible: [...catalogueKeys], hidden: [] }
  const seen = new Set<string>()
  const visible: string[] = []
  for (const key of layout) {
    if (!catalogueKeys.includes(key) || seen.has(key) || visible.length >= WORKBENCH_MAX_ENTRIES) continue
    seen.add(key)
    visible.push(key)
  }
  return { visible, hidden: catalogueKeys.filter(key => !seen.has(key)) }
}
