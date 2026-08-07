import request from '@/api/request'

export interface ExchangeRateStatistics {
  min: number
  max: number
  avg: number
  count: number
  std: number
}

export interface ExchangeRateTrend {
  slope: number
  direction: 'up' | 'down' | 'stable'
}

export interface ExchangeRateChartPoint {
  timestamp: string
  rate: number
}

export interface ExchangeRateDashboard {
  record_count: number
  latest_rate: number
  latest_time: string | null
  today_high: number | null
  today_low: number | null
  data_freshness_seconds: number | null
}

export interface ExchangeRateRecord {
  timestamp: string
  rate: number
}

export const exchangeRateApi = {
  getCount() {
    return request.get<number>('/exchange-rate/count')
  },

  getStatistics(params?: { hours?: number; start_date?: string; end_date?: string }) {
    return request.get<ExchangeRateStatistics>('/exchange-rate/statistics', { params })
  },

  getTrend(params?: { hours?: number; start_date?: string; end_date?: string }) {
    return request.get<ExchangeRateTrend>('/exchange-rate/trend', { params })
  },

  getDashboard(params?: { hours?: number; start_date?: string; end_date?: string }) {
    return request.get<ExchangeRateDashboard>('/exchange-rate/dashboard', { params })
  },

  getChart(params?: { hours?: number; start_date?: string; end_date?: string }) {
    return request.get<ExchangeRateChartPoint[]>('/exchange-rate/chart', { params })
  },

  getRecent(params?: { hours?: number; limit?: number }) {
    return request.get<ExchangeRateRecord[]>('/exchange-rate/recent', { params })
  },
}
