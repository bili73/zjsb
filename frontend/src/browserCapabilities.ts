// HTTP deployments lack some secure-context APIs; preserve the same data contracts.
import { sha256 } from '@noble/hashes/sha2.js'
import { bytesToHex } from '@noble/hashes/utils.js'

export function randomId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 15) | 64
  bytes[8] = (bytes[8]! & 63) | 128
  const hex = bytesToHex(bytes)
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  if (crypto.subtle) return bytesToHex(new Uint8Array(await crypto.subtle.digest('SHA-256', data)))
  const bytes = new Uint8Array(data), hash = sha256.create(), chunk = 1024 * 1024
  try {
    for (let offset = 0; offset < bytes.length; offset += chunk) {
      hash.update(bytes.subarray(offset, offset + chunk))
      if (offset + chunk < bytes.length) await new Promise(resolve => setTimeout(resolve, 0))
    }
    return bytesToHex(hash.digest())
  } finally { hash.destroy() }
}

export async function copyText(value: string, current: () => boolean = () => true): Promise<void> {
  if (!current()) throw new Error('COPY_CANCELLED')
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(value); return }
    catch { /* Continue only while the initiating view is still current. */ }
  }
  if (!current()) throw new Error('COPY_CANCELLED')
  // No await here: HTTP copy must stay inside the user gesture. Keep focus inside
  // the active dialog so its focus trap cannot steal the temporary selection.
  const active = document.activeElement as HTMLElement | null
  const field = document.createElement('textarea')
  field.value = value; field.readOnly = true
  field.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none'
  try {
    (active?.closest('[role="dialog"], [role="alertdialog"]') ?? document.body).appendChild(field)
    field.focus({ preventScroll: true }); field.select()
    if (!document.execCommand('copy')) throw new Error('COPY_UNAVAILABLE')
  } finally {
    field.remove()
    if (active?.isConnected) active.focus({ preventScroll: true })
  }
}
