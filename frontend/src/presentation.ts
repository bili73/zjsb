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
