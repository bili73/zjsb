// Ordered account preferences; no shared browser storage or legacy-key import.
// 所有布局最多展示十二项；其余类型收纳，识别类型总数不受展示容量限制。

export const WORKBENCH_MAX_ENTRIES = 12
// Accept all fourteen catalogue keys, including unchanged older preferences.
const STORED_LAYOUT_MAX_KEYS = 14
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
      !(v.layout === null || Array.isArray(v.layout) && v.layout.length <= STORED_LAYOUT_MAX_KEYS &&
        v.layout.every(key => typeof key === 'string' && /^[A-Z_]{1,64}$/.test(key)) && new Set(v.layout).size === v.layout.length)) {
    throw new Error('INVALID_RESPONSE')
  }
  return { layout: v.layout === null ? null : [...v.layout!], revision: v.revision! }
}

// layout 为 null 时也按目录顺序执行十二项上限。
// 自定义里的未知键（已下线类型）被忽略，重复键去重，超出上限的尾部键收纳。
export function splitEntries(catalogueKeys: readonly string[], layout: readonly string[] | null): { visible: string[]; hidden: string[] } {
  const seen = new Set<string>()
  const visible: string[] = []
  for (const key of layout ?? catalogueKeys) {
    if (!catalogueKeys.includes(key) || seen.has(key) || visible.length >= WORKBENCH_MAX_ENTRIES) continue
    seen.add(key)
    visible.push(key)
  }
  return { visible, hidden: catalogueKeys.filter(key => !seen.has(key)) }
}
