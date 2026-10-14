// 工作台入口自定义：展示哪些识别类型、按什么顺序，保存在本机浏览器（localStorage）。
// 没有自定义记录时展示全部类型；自定义后，后续新增类型默认收纳，避免工作台越来越挤。

export const WORKBENCH_MAX_ENTRIES = 12
export const WORKBENCH_LAYOUT_KEY = 'ocr-workbench-entries-v1'

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

export function loadWorkbenchLayout(storage: Pick<Storage, 'getItem'> | null | undefined): string[] | null {
  try {
    const raw = storage?.getItem(WORKBENCH_LAYOUT_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.some(key => typeof key !== 'string')) return null
    return parsed as string[]
  } catch {
    return null
  }
}

export function saveWorkbenchLayout(storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null | undefined, layout: readonly string[] | null): void {
  try {
    if (!storage) return
    if (layout === null) storage.removeItem(WORKBENCH_LAYOUT_KEY)
    else storage.setItem(WORKBENCH_LAYOUT_KEY, JSON.stringify([...layout]))
  } catch {
    // 隐私模式或配额不足时放弃记忆，不影响本次使用。
  }
}
