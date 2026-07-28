import request from '@/api/request'

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
}

export interface DashboardResponse {
  total_records: number
  symbols: SymbolDashboardItem[]
}

export interface PriceRecord {
  id: number
  symbol: string
  price: number
  timestamp: string
}

export const priceApi = {
  getDashboard() {
    return request.get<DashboardResponse>('/prices/dashboard')
  },
  getStatistics(symbol: string, hours = 24) {
    return request.get<PriceStatistics>('/prices/statistics', { params: { symbol, hours } })
  },
  getTrend(symbol: string, hours = 6) {
    return request.get<PriceTrend>('/prices/trend', { params: { symbol, hours } })
  },
  getChart(symbol: string, hours = 24) {
    return request.get<PriceChartPoint[]>('/prices/chart', { params: { symbol, hours } })
  },
  getRecent(symbol: string, limit = 20) {
    return request.get<PriceRecord[]>('/prices/recent', { params: { symbol, limit } })
  },
  getCount(symbol: string) {
    return request.get<number>('/prices/count', { params: { symbol } })
  },
}
