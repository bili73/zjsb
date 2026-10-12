import type { Classification } from './business.ts'

// Serial preview work. Removed/manual rows invalidate their pending response.
export function createClassificationQueue(
  classify: (file: File, signal: AbortSignal) => Promise<Classification>,
  update: (uid: number, result: Classification | null, processing: boolean) => void,
  failed: (error: unknown) => void = () => {},
) {
  const pending = new Map<number, { file: File; controller: AbortController }>()
  let running = false, disposed = false
  async function drain() {
    if (running || disposed) return
    running = true
    try {
      while (pending.size && !disposed) {
        const [uid, entry] = pending.entries().next().value!
        update(uid, null, true)
        try {
          const result = await classify(entry.file, entry.controller.signal)
          if (!disposed && pending.get(uid) === entry && !entry.controller.signal.aborted) update(uid, result, false)
        } catch (error) {
          if (!disposed && pending.get(uid) === entry && !entry.controller.signal.aborted) {
            update(uid, null, false)
            failed(error)
          }
        } finally { if (pending.get(uid) === entry) pending.delete(uid) }
      }
    } finally { running = false }
  }
  function remove(uid: number) { pending.get(uid)?.controller.abort(); pending.delete(uid) }
  return {
    add(uid: number, file: File) {
      if (disposed) return
      remove(uid)
      pending.set(uid, { file, controller: new AbortController() })
      void drain()
    },
    remove,
    dispose() { disposed = true; for (const uid of pending.keys()) remove(uid) },
  }
}
