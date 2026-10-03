import request from '@/api/request'

export type PlanStatus = 'active' | 'paused' | 'done' | 'cancelled'

export interface PurchaseLot {
  id: number
  symbol: string
  trade_date: string
  grams: number
  price_per_gram: number
  fee: number
  channel: string
  note: string
  plan_id: number | null
  created_at: string
  /** 后端派生字段：克数 × 单价，不含手续费 */
  amount: number
}

export interface PurchaseLotPayload {
  symbol: string
  trade_date: string
  grams: number
  price_per_gram: number
  fee?: number
  channel?: string
  note?: string
  plan_id?: number | null
}

export type PurchaseLotUpdate = Partial<PurchaseLotPayload>

export interface PurchasePlan {
  id: number
  symbol: string
  target_grams: number
  budget: number | null
  tranches: number
  tranche_grams: number | null
  trigger_policy: Record<string, unknown>
  start_date: string | null
  end_date: string | null
  status: PlanStatus
  created_at: string
  updated_at: string
}

export interface PurchasePlanPayload {
  symbol: string
  target_grams: number
  budget?: number | null
  tranches?: number
  tranche_grams?: number | null
  trigger_policy?: Record<string, unknown>
  start_date?: string | null
  end_date?: string | null
  status?: PlanStatus
}

export interface PositionSummary {
  symbol: string
  lot_count: number
  total_grams: number
  total_cost: number
  total_fee: number
  avg_cost: number
  latest_price: number | null
  market_value: number | null
  unrealized_pnl: number | null
  unrealized_pnl_pct: number | null
  first_trade_date: string | null
  last_trade_date: string | null
}

export interface PlanProgress {
  plan_id: number
  symbol: string
  target_grams: number
  filled_grams: number
  remaining_grams: number
  progress_pct: number
  tranches: number
  filled_tranches: number
  invested_amount: number
  avg_cost: number
  status: PlanStatus
  start_date: string | null
  end_date: string | null
}

export interface PortfolioSummary {
  positions: PositionSummary[]
  plans: PlanProgress[]
  total_grams: number
  total_cost: number
  total_fee: number
  /** 任一品种拿不到行情时为 null，不要当成 0 */
  total_market_value: number | null
  total_unrealized_pnl: number | null
  total_unrealized_pnl_pct: number | null
  priced_symbols: string[]
}

export const portfolioApi = {
  // ---- 买入批次 ----
  listLots(symbol?: string) {
    return request.get<PurchaseLot[]>('/portfolio/lots', { params: { symbol } })
  },

  createLot(payload: PurchaseLotPayload) {
    return request.post<PurchaseLot>('/portfolio/lots', payload)
  },

  updateLot(id: number, payload: PurchaseLotUpdate) {
    return request.put<PurchaseLot>(`/portfolio/lots/${id}`, payload)
  },

  deleteLot(id: number) {
    return request.delete<null>(`/portfolio/lots/${id}`)
  },

  // ---- 购买计划 ----
  listPlans(params?: { symbol?: string; status?: PlanStatus }) {
    return request.get<PurchasePlan[]>('/portfolio/plans', { params })
  },

  createPlan(payload: PurchasePlanPayload) {
    return request.post<PurchasePlan>('/portfolio/plans', payload)
  },

  updatePlan(id: number, payload: Partial<PurchasePlanPayload>) {
    return request.put<PurchasePlan>(`/portfolio/plans/${id}`, payload)
  },

  deletePlan(id: number) {
    return request.delete<null>(`/portfolio/plans/${id}`)
  },

  // ---- 持仓总览 ----
  getSummary(symbol?: string) {
    return request.get<PortfolioSummary>('/portfolio/summary', { params: { symbol } })
  }
}
