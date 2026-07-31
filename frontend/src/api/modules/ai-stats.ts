import request from '@/api/request'

export interface AiStatsOverview {
  today_total: number
  today_success: number
  today_failure: number
  success_rate: number
  failure_rate: number
  consecutive_failures: number
  last_success_time: string | null
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
  timeout_rate: number
  total_all: number
  cache_hit_count: number
  cache_hit_rate: number
  top_model: { provider: string; model: string; count: number } | null
  top_provider: { provider: string; count: number } | null
  top_failures: { reason: string; count: number }[]
  hourly_distribution: { hour: string; count: number }[]
  model_ranking: {
    provider: string
    model: string
    total: number
    success_rate: number
    avg_latency: number
  }[]
  provider_ranking: { provider: string; total: number; success_rate: number; avg_latency: number }[]
  provider_failures: { provider: string; count: number }[]
}

export interface DailyTrendItem {
  date: string
  hour: string | null
  total: number
  success_count: number
  success_rate: number
  avg_latency: number
}

export interface AiCallLogItem {
  id: number
  provider_name: string
  model_name: string
  call_time: string
  success: boolean
  latency_ms: number | null
  error_reason: string | null
  from_cache: boolean
  triggered_alerts: string | null
  raw_response: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface AiCallLogsResponse {
  items: AiCallLogItem[]
  total: number
  page: number
  page_size: number
}

export interface TokenOverview {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  calls: number
  estimated_cost: number
}

export interface TokenByModel {
  provider_name: string
  model_name: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  calls: number
  estimated_cost: number
}

export interface TokenTrendItem {
  date: string
  hour: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  calls: number
  estimated_cost: number
}

export interface DateParams {
  start_date: string
  end_date: string
}

export const aiStatsApi = {
  getOverview(params: DateParams) {
    return request.get<AiStatsOverview>('/ai-stats/overview', { params })
  },
  getTrend(params: DateParams) {
    return request.get<DailyTrendItem[]>('/ai-stats/trend', { params })
  },
  getLogs(page = 1, pageSize = 20, dateParams?: DateParams) {
    return request.get<AiCallLogsResponse>('/ai-stats/logs', {
      params: { page, page_size: pageSize, ...dateParams },
    })
  },
  getTokenOverview(params: DateParams) {
    return request.get<TokenOverview>('/ai-stats/tokens/overview', { params })
  },
  getTokenByModel(params: DateParams) {
    return request.get<TokenByModel[]>('/ai-stats/tokens/by-model', { params })
  },
  getTokenTrend(params: DateParams) {
    return request.get<TokenTrendItem[]>('/ai-stats/tokens/trend', { params })
  },
}
