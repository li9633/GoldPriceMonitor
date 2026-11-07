export function formatPrice(price: number, decimals = 2): string {
  return `¥${price.toFixed(decimals)}`
}

export function formatChangePercent(value: number): string {
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** ISO 时间戳原样转可读（仅替换 T 为空格，不做时区转换） */
export function formatIsoTime(iso: string): string {
  return iso.replace('T', ' ')
}

const pad = (n: number) => String(n).padStart(2, '0')

export function toDateString(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function today(): string {
  return toDateString(new Date())
}

export function offsetDate(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return toDateString(d)
}
