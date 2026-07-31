import type { DailyTrendItem, TokenTrendItem } from '@/api/modules/ai-stats'
import { toDateString } from '@/utils/format'

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

export function getDaysBetween(start: string, end: string): number {
  const diff = new Date(end).getTime() - new Date(start).getTime()
  return Math.round(diff / (1000 * 60 * 60 * 24)) + 1
}

export function fillEmptyDates(
  data: DailyTrendItem[],
  startDate: string,
  endDate: string,
): DailyTrendItem[] {
  const days = getDaysBetween(startDate, endDate)
  const result: DailyTrendItem[] = []
  const start = new Date(startDate)
  for (let i = 0; i < days; i++) {
    const d = new Date(start)
    d.setDate(d.getDate() + i)
    const dateStr = toDateString(d)
    const found = data.find((item) => item.date === dateStr)
    result.push(
      found || {
        date: dateStr,
        hour: null,
        total: 0,
        success_count: 0,
        success_rate: 0,
        avg_latency: 0,
      },
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

export function fillEmptyTokenDates(
  data: TokenTrendItem[],
  startDate: string,
  endDate: string,
): TokenTrendItem[] {
  const days = getDaysBetween(startDate, endDate)
  const result: TokenTrendItem[] = []
  const start = new Date(startDate)
  for (let i = 0; i < days; i++) {
    const d = new Date(start)
    d.setDate(d.getDate() + i)
    const dateStr = toDateString(d)
    const found = data.find((item) => item.date === dateStr)
    result.push(
      found || {
        date: dateStr,
        hour: null,
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        calls: 0,
        estimated_cost: 0,
      },
    )
  }
  return result
}

export function fillEmptyTrendHours(data: DailyTrendItem[]): DailyTrendItem[] {
  const result: DailyTrendItem[] = []
  for (let h = 0; h < 24; h++) {
    const hourStr = String(h).padStart(2, '0')
    const found = data.find((item) => item.hour === hourStr)
    result.push(
      found || {
        date: data[0]?.date ?? '',
        hour: hourStr,
        total: 0,
        success_count: 0,
        success_rate: 0,
        avg_latency: 0,
      },
    )
  }
  return result
}

export function fillEmptyTokenHours(data: TokenTrendItem[]): TokenTrendItem[] {
  const result: TokenTrendItem[] = []
  for (let h = 0; h < 24; h++) {
    const hourStr = String(h).padStart(2, '0')
    const found = data.find((item) => item.hour === hourStr)
    result.push(
      found || {
        date: data[0]?.date ?? '',
        hour: hourStr,
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        calls: 0,
        estimated_cost: 0,
      },
    )
  }
  return result
}
