import request from '@/api/request'
import type { PositionSummary } from '@/api/modules/portfolio'

export type AdviceAction =
  'BUY_NOW' | 'BUY_PARTIAL' | 'WAIT' | 'AVOID' | 'HOLD' | 'ADD' | 'TAKE_PROFIT' | 'STOP_LOSS'

export type AdviceKind = 'pre_purchase' | 'post_purchase' | 'plan_execution' | 'review'

export type AdviceStatus = 'delivered' | 'acknowledged' | 'acted' | 'expired' | 'suppressed'

export type SignalCategory = 'market' | 'position' | 'plan'

export interface AdviceSignal {
  id: string
  category: SignalCategory
  severity: 'info' | 'notice' | 'warning' | 'critical' | string
  summary: string
  metrics: Record<string, unknown>
}

export interface AdviceRecord {
  id: number
  created_at: string
  kind: AdviceKind
  action: AdviceAction
  symbol: string
  /** 本次建议买入/卖出的克数；null 表示只能给方向、给不出数量 */
  target_grams: number | null
  price_band_low: number | null
  price_band_high: number | null
  confidence: number
  rationale: string
  signals: AdviceSignal[]
  /** 冻结的行情与持仓快照，用于事后回溯 */
  evidence: Record<string, unknown>
  model_info: string
  status: AdviceStatus
  suppressed_reason: string
  acted_lot_id: number | null
  price_at_advice: number | null
  price_t1: number | null
  price_t7: number | null
  price_t30: number | null
  reviewed_at: string | null
}

export interface AdviceNowResponse {
  advice: AdviceRecord
  symbol: string
  current_price: number
  position: PositionSummary
  plan_progress: unknown[]
  /** 是否配了总资金/目标克数 —— 决定建议能否给出具体克数 */
  prefs_configured: boolean
}

export interface AdviceReviewStats {
  total: number
  with_t1: number
  with_t7: number
  with_t30: number
  avg_move_t1_pct: number | null
  avg_move_t7_pct: number | null
  avg_move_t30_pct: number | null
}

export interface AdviceConfig {
  enabled: boolean
  total_investable: number
  target_grams: number
  target_position_ratio: number
  risk_level: string
  enable_llm: boolean
  price_move_trigger_pct: number
}

export const adviceApi = {
  /** 手动请求一条建议；fast=true 跳过 AI 措辞，只返回规则结论 */
  getNow(params?: { symbol?: string; fast?: boolean }) {
    return request.get<AdviceNowResponse>('/advice/now', { params })
  },

  getHistory(params?: {
    symbol?: string
    kind?: AdviceKind
    status?: AdviceStatus
    page?: number
    page_size?: number
  }) {
    return request.get<{
      items: AdviceRecord[]
      total: number
      page: number
      page_size: number
      total_pages: number
    }>('/advice/history', { params })
  },

  get(id: number) {
    return request.get<AdviceRecord>(`/advice/${id}`)
  },

  acknowledge(id: number) {
    return request.post<AdviceRecord>(`/advice/${id}/ack`)
  },

  markActed(id: number, lotId?: number) {
    return request.post<AdviceRecord>(`/advice/${id}/acted`, undefined, {
      params: { lot_id: lotId }
    })
  },

  refreshReviews() {
    return request.post<{ checked: number; filled: number }>('/advice/reviews/refresh')
  },

  getReviewStats() {
    return request.get<AdviceReviewStats>('/advice/reviews/stats')
  },

  // 建议偏好走设置接口，但归建议域维护
  getConfig() {
    return request.get<AdviceConfig>('/settings/advice')
  },

  updateConfig(data: AdviceConfig) {
    return request.put<AdviceConfig>('/settings/advice', data)
  }
}
