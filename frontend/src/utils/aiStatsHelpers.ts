import type { DailyTrendItem } from '@/api/modules/ai-stats'

export function isDark(): boolean {
  return document.documentElement.getAttribute('data-theme') === 'dark'
}

export function axisColor(): string {
  return isDark() ? '#a09070' : '#8c7a5c'
}

export function splitColor(): string {
  return isDark() ? '#2a2a40' : '#e8e0d0'
}

export function formatLatency(ms: number): string {
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return ms.toFixed(0) + 'ms'
}

export function rateColor(rate: number): string {
  if (rate >= 95) return '#67c23a'
  if (rate >= 80) return '#e6a23c'
  return '#f56c6c'
}

export function latencyColor(ms: number): string {
  if (ms < 1000) return '#67c23a'
  if (ms < 3000) return '#e6a23c'
  return '#f56c6c'
}

export function fillEmptyDates(data: DailyTrendItem[], days: number): DailyTrendItem[] {
  const result: DailyTrendItem[] = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = d.toISOString().slice(0, 10)
    const found = data.find((item) => item.date === dateStr)
    result.push(
      found || { date: dateStr, total: 0, success_count: 0, success_rate: 0, avg_latency: 0 },
    )
  }
  return result
}

export function fillEmptyHours(data: { hour: string; count: number }[]): number[] {
  const counts = new Array(24).fill(0)
  data.forEach((item) => {
    const h = parseInt(item.hour, 10)
    if (h >= 0 && h < 24) counts[h] = item.count
  })
  return counts
}
