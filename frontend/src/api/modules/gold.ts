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

export interface PriceSnapshot {
  symbol: string
  current_price: number
  statistics_24h: PriceStatistics | null
  trend_6h: PriceTrend | null
  trend_24h: PriceTrend | null
  ma_5: number | null
  ma_10: number | null
  ma_20: number | null
  min_3m: number | null
  min_6m: number | null
  recent_prices: number[]
}

export interface PriceRecord {
  id: number
  symbol: string
  price: number
  timestamp: string
}

export const priceApi = {
  getSnapshot(symbol: string) {
    return request.get<PriceSnapshot>('/prices/snapshot', {
      params: { symbol },
    })
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
