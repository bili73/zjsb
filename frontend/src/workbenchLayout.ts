import { reactive } from 'vue'
import { ApiFailure, isAbort } from './api.ts'
import type { BusinessApi } from './api.ts'

type Client = Pick<BusinessApi, 'workbenchLayout' | 'saveWorkbenchLayout' | 'saveWorkbenchDefault'>

// Session-scoped draft: late responses cannot restore a previous account's UI.
export function createWorkbenchLayout(onUnauthorized: () => void) {
  const initial = () => ({ layout: null as string[] | null, revision: 0, loaded: false,
    defaults: { layout: null as string[] | null, revision: 0 }, defaultConflict: false,
    loading: false, saving: false, editing: false, conflict: false, error: '' })
  const state = reactive(initial())
  let client: Client | null = null
  let generation = 0
  let controller: AbortController | undefined
  function invalidate() { generation++; controller?.abort(); controller = undefined }
  function dispose() { invalidate(); client = null; Object.assign(state, initial()) }

  async function load() {
    if (!client || state.saving) return false
    invalidate()
    const version = generation
    controller = new AbortController()
    state.loading = true
    state.loaded = false
    state.error = ''
    try {
      const result = await client.workbenchLayout(controller.signal)
      if (version !== generation) return false
      Object.assign(state, result, { loaded: true, editing: false, conflict: false, defaultConflict: false })
      return true
    } catch (error) {
      if (version !== generation || isAbort(error)) return false
      state.error = '个人布局读取失败，可重试；读取成功前暂不能自定义。'
      if (error instanceof ApiFailure && error.card.http_status === 401) onUnauthorized()
      return false
    } finally { if (version === generation) state.loading = false }
  }

  function bind(next: Client | null) {
    dispose()
    client = next
    if (client) void load()
  }

  async function persist(target: 'personal' | 'default', defaultLayout: string[] | null = null) {
    if (!client || !state.loaded || !state.editing || state.loading || state.saving ||
        (target === 'personal' ? state.conflict : state.defaultConflict)) return false
    invalidate()
    const version = generation
    controller = new AbortController()
    state.saving = true
    state.error = ''
    try {
      if (target === 'default') {
        const result = await client.saveWorkbenchDefault({ layout: defaultLayout === null ? null : [...defaultLayout], expected_revision: state.defaults.revision }, controller.signal)
        if (version !== generation) return false
        state.defaults = result
        if (state.conflict) state.error = '此账号的布局已在其他页面修改。当前调整已保留，请重新读取后再调整。'
      } else {
        const body = { layout: state.layout === null ? null : [...state.layout], expected_revision: state.revision }
        const result = await client.saveWorkbenchLayout(body, controller.signal)
        if (version !== generation) return false
        Object.assign(state, result, { editing: false, defaultConflict: false })
      }
      return true
    } catch (error) {
      if (version !== generation || isAbort(error)) return false
      const conflict = error instanceof ApiFailure && error.card.http_status === 409
      if (target === 'default') {
        state.defaultConflict = conflict
        state.error = conflict ? '默认布局已被其他管理员修改。当前调整已保留，请重新读取后再调整。'
          : '默认布局保存未确认，当前调整已保留。可重试保存；若提示冲突，请重新读取。'
      } else {
        state.conflict = conflict
        state.error = conflict ? '此账号的布局已在其他页面修改。当前调整已保留，请重新读取后再调整。'
          : '布局保存未确认，当前调整已保留。可重试保存；若提示冲突，请重新读取。'
      }
      if (error instanceof ApiFailure && error.card.http_status === 401) onUnauthorized()
      return false
    } finally { if (version === generation) state.saving = false }
  }
  return { state, bind, load, save: () => persist('personal'),
    saveDefault: (layout: string[] | null) => persist('default', layout), dispose }
}
