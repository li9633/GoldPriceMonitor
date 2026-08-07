import request from '@/api/request'
import type { ExchangeRateDashboard } from './exchange-rate'

export interface PriceStatistics {
  min: number
  max: number
  avg: number
  count: number
  std: number
}

export interface PriceTrend {
  slope: number
  direction: 'up' | 'down' | 'stable'
}

export interface PriceChartPoint {
  timestamp: string
  price: number
}

export interface SymbolDashboardItem {
  symbol: string
  name: string
  count: number
  latest_price: number | null
  latest_time: string | null
  today_high: number | null
  today_low: number | null
  data_freshness_seconds: number | null
}

export interface DashboardResponse {
  start_date: string
  end_date: string
  price: {
    total_records: number
    new_records: number
    symbols: SymbolDashboardItem[]
  }
  ai: {
    total_calls: number
    success_count: number
    failure_count: number
    success_rate: number
    cache_hit_count: number
    total_tokens: number
    last_success_time: string | null
  }
  notification: {
    total_sends: number
    success_count: number
    failure_count: number
    success_rate: number
  }
  active_symbols_count: number
  monitored_symbols: string[]
  main_symbol: string
  exchange_rate: ExchangeRateDashboard
}

export interface DashboardParams {
  hours?: number
  start_date?: string
  end_date?: string
}

export interface PriceRecord {
  id: number
  symbol: string
  price: number
  timestamp: string
}

export const priceApi = {
  getDashboard(params?: DashboardParams) {
    return request.get<DashboardResponse>('/prices/dashboard', { params })
  },
  getStatistics(symbol: string, hours?: number, start_date?: string, end_date?: string) {
    return request.get<PriceStatistics>('/prices/statistics', {
      params: { symbol, hours, start_date, end_date },
    })
  },
  getTrend(symbol: string, hours?: number) {
    return request.get<PriceTrend>('/prices/trend', { params: { symbol, hours } })
  },
  getChart(symbol: string, hours?: number, start_date?: string, end_date?: string) {
    return request.get<PriceChartPoint[]>('/prices/chart', {
      params: { symbol, hours, start_date, end_date },
    })
  },
  getRecent(symbol: string, limit = 20) {
    return request.get<PriceRecord[]>('/prices/recent', { params: { symbol, limit } })
  },
  getCount(symbol: string) {
    return request.get<number>('/prices/count', { params: { symbol } })
  },
}
