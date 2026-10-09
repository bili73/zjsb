import { computed, reactive } from 'vue'
import { recordDiagnostic, setDiagnosticVersion } from './diagnostics.ts'
import { needsStartupRefresh, parseHealth } from './health.ts'
import type { Health } from './health.ts'

export type EngineConnection = 'connecting' | 'connected' | 'disconnected' | 'invalid'
export type EngineTone = 'success' | 'warning' | 'danger' | 'info'

// Shared health snapshot: the header badge and the engine page read the same
// state. Auto-refresh continues only while startup/stopping is in progress.
export function createEngine(fetcher: typeof fetch = fetch) {
  const state = reactive({
    health: null as Health | null,
    connection: 'connecting' as EngineConnection,
    refreshing: false,
    lastCheckedAt: null as string | null,
    auto: false,
  })
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined
  let disposed = false

  async function refresh() {
    if (state.refreshing || disposed) return
    clearTimeout(timer)
    controller = new AbortController()
    state.refreshing = true
    const timeout = setTimeout(() => controller?.abort(), 5000)
    let responseStatus: number | undefined
    let requestId: string | null = null
    try {
      const response = await fetcher.call(globalThis, '/health', { signal: controller.signal, cache: 'no-store', credentials: 'same-origin' })
      responseStatus = response.status
      requestId = response.headers.get('X-Request-ID')
      if (!response.ok) throw new Error('CONNECTION_FAILED')
      const body: unknown = await response.json().catch(() => { throw new Error('INVALID_HEALTH') })
      const health = parseHealth(body)
      if (disposed) return
      state.health = health
      state.connection = 'connected'
      state.lastCheckedAt = new Date().toISOString()
      setDiagnosticVersion(health.version)
      state.auto = needsStartupRefresh(health)
      if (state.auto) timer = setTimeout(refresh, 1000)
    } catch (error) {
      if (disposed) return
      state.health = null
      state.auto = false
      state.connection = error instanceof Error && error.message === 'INVALID_HEALTH' ? 'invalid' : 'disconnected'
      recordDiagnostic({ origin: 'http', operation: 'health', code: state.connection === 'invalid' ? 'INVALID_RESPONSE' : 'NETWORK_ERROR', status: responseStatus, request_id: requestId })
    } finally {
      clearTimeout(timeout)
      state.refreshing = false
    }
  }

  const summary = computed<{ tone: EngineTone; label: string }>(() => {
    if (state.connection === 'connecting') return { tone: 'info', label: '连接中' }
    if (state.connection === 'disconnected') return { tone: 'danger', label: '服务未连接' }
    if (state.connection === 'invalid') return { tone: 'warning', label: '状态解析异常' }
    const health = state.health
    const runtime = health?.runtime
    if (!health) return { tone: 'info', label: '状态未知' }
    if (runtime?.state === 'starting') return { tone: 'info', label: '引擎启动中' }
    if (runtime?.state === 'stopping') return { tone: 'info', label: '引擎停止中' }
    if (runtime?.effective_mode === 'ocr_unavailable') return { tone: 'danger', label: 'OCR 不可用' }
    if (runtime?.state === 'degraded') return { tone: 'warning', label: '引擎能力受限' }
    if (health.status === 'ok' && runtime?.state === 'ready') return { tone: 'success', label: '引擎就绪' }
    if (health.status === 'ok') return { tone: 'success', label: '服务正常' }
    return { tone: 'warning', label: '部分组件未就绪' }
  })

  function refreshWhenVisible() { if (typeof document === 'undefined' || !document.hidden) void refresh() }
  function wentOffline() {
    clearTimeout(timer)
    controller?.abort()
    state.health = null
    state.auto = false
    state.connection = 'disconnected'
  }

  function install() {
    if (typeof window === 'undefined') return
    window.addEventListener('focus', refreshWhenVisible)
    window.addEventListener('online', refreshWhenVisible)
    window.addEventListener('offline', wentOffline)
  }
  function dispose() {
    disposed = true
    clearTimeout(timer)
    controller?.abort()
    if (typeof window === 'undefined') return
    window.removeEventListener('focus', refreshWhenVisible)
    window.removeEventListener('online', refreshWhenVisible)
    window.removeEventListener('offline', wentOffline)
  }

  return { state, summary, refresh, install, dispose }
}
export type Engine = ReturnType<typeof createEngine>
