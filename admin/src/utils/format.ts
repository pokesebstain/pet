export function formatDateTime(d: string | Date | null | undefined): string {
  if (!d) return '-'
  const date = typeof d === 'string' ? new Date(d) : d
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatDate(d: string | Date | null | undefined): string {
  if (!d) return '-'
  const date = typeof d === 'string' ? new Date(d) : d
  return date.toLocaleDateString('zh-CN')
}

export function formatTime(hhmm: string | null | undefined): string {
  return hhmm || '-'
}
